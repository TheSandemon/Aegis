"""
integrations/manager.py
Central coordinator for all column-bound external service integrations.

Responsibilities:
  - Load integrations from DB at startup (one per column that has integration_type set)
  - Manage per-integration asyncio polling loops
  - Route inbound webhooks to the correct adapter
  - Call sync_out when Aegis cards change (write/read_write mode columns)
  - Expose status for GET /api/integrations
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger("aegis.integrations.manager")


class IntegrationManager:

    def __init__(self, store, broadcaster):
        self.store = store
        self.broadcaster = broadcaster
        # column_id → BaseIntegration instance
        self._integrations: Dict[int, object] = {}
        # column_id → asyncio.Task (polling loop)
        self._poll_tasks: Dict[int, asyncio.Task] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self):
        """Called at app startup. Loads integrations for all configured columns."""
        columns = self.store.get_columns()
        for col in columns:
            if col.get("integration_type"):
                try:
                    await self._activate(col["id"], col)
                except Exception as e:
                    logger.error(f"Failed to start integration for column {col['id']}: {e}")
        logger.info(f"IntegrationManager ready — {len(self._integrations)} integration(s) active")

    async def setup_integration(self, column_id: int, col_data: dict):
        """
        Called when a column with an integration is created, or when its config is updated.
        col_data should contain flat keys matching the column table fields:
          integration_type, integration_mode, integration_credentials (JSON str),
          integration_filters (JSON str), sync_interval_ms, webhook_secret
        plus 'name' for the column display name.
        """
        await self.teardown_integration(column_id)

        # Persist config to DB before activating
        self.store.update_column_integration(
            column_id,
            integration_type=col_data.get("integration_type"),
            integration_mode=col_data.get("integration_mode", "read"),
            integration_credentials=col_data.get("integration_credentials"),
            integration_filters=col_data.get("integration_filters"),
            sync_interval_ms=col_data.get("sync_interval_ms", 60000),
            webhook_secret=col_data.get("webhook_secret"),
            integration_status="active",
        )

        # Re-fetch so we have a complete column dict
        col = self.store.get_column_by_id(column_id)
        if col:
            await self._activate(column_id, col)

    async def teardown_integration(self, column_id: int):
        """Called when a column is deleted or its integration is being replaced."""
        if column_id in self._poll_tasks:
            self._poll_tasks[column_id].cancel()
            try:
                await self._poll_tasks[column_id]
            except asyncio.CancelledError:
                pass
            del self._poll_tasks[column_id]

        if column_id in self._integrations:
            try:
                await self._integrations[column_id].deregister_webhook()
            except Exception:
                pass
            del self._integrations[column_id]

        # Clear integration fields from DB
        self.store.update_column_integration(
            column_id,
            integration_type=None,
            integration_mode="read",
            integration_credentials=None,
            integration_filters=None,
            integration_status=None,
            last_synced_at=None,
        )

    # ── Inbound webhook routing ──────────────────────────────────────────────

    async def handle_webhook(self, column_id: int, request) -> Optional[dict]:
        """
        Route an inbound webhook POST to the correct integration adapter.
        `request` is a FastAPI Request object.
        Returns the upserted card or None if the event was ignored.
        """
        integration = self._integrations.get(column_id)
        if not integration:
            return None

        raw_body = await request.body()
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = {}
        headers = dict(request.headers)
        headers["_raw_body"] = raw_body  # passed for HMAC verification

        return await integration.handle_webhook(payload, headers)

    # ── Outbound change notification ─────────────────────────────────────────

    async def notify_card_change(self, card: dict, event_type: str):
        """
        Called after PATCH /api/cards or POST /api/cards/{id}/comments.
        Finds the column integration for the card's current column and calls sync_out
        if the integration mode includes write.
        """
        col_name = card.get("column")
        for col_id, integration in self._integrations.items():
            if integration.column_name == col_name:
                # Always propagate deletions to prevent deleted cards re-appearing on next sync
                should_sync_out = (
                    integration.mode in ("write", "read_write") or
                    event_type == "card_deleted"
                )
                if should_sync_out:
                    try:
                        await integration.sync_out(card, event_type)
                    except Exception as e:
                        logger.error(f"sync_out failed for column {col_id}: {e}")
                break

    # ── Initial sync after setup ─────────────────────────────────────────────

    async def initial_sync(self, column_id: int):
        """
        Called once immediately after setup_integration to validate credentials
        and pull initial data. Broadcasts integration_status on success or error.
        """
        integration = self._integrations.get(column_id)
        if not integration or integration.mode not in ("read", "read_write"):
            return
        try:
            results = await integration.sync_in()
            now = datetime.now().isoformat()
            self.store.update_column_integration(
                column_id,
                last_synced_at=now,
                integration_status="active",
            )
            count = len(results) if results else 0
            logger.info(f"Initial sync for column {column_id}: {count} item(s)")
            await self.broadcaster({
                "type": "integration_status",
                "column_id": column_id,
                "status": "active",
                "last_synced_at": now,
                "synced_count": count,
            })
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Initial sync failed for column {column_id}: {error_msg}")
            self.store.update_column_integration(column_id, integration_status="error")
            await self.broadcaster({
                "type": "integration_status",
                "column_id": column_id,
                "status": "error",
                "error": error_msg,
            })

    # ── Manual sync ──────────────────────────────────────────────────────────

    async def force_sync(self, column_id: int) -> list:
        """Called from POST /api/integrations/{column_id}/sync."""
        integration = self._integrations.get(column_id)
        if not integration:
            return []
        if integration.mode in ("read", "read_write"):
            results = await integration.sync_in()
            self.store.update_column_integration(
                column_id, last_synced_at=datetime.now().isoformat()
            )
            return results
        return []

    # ── Status for GET /api/integrations ─────────────────────────────────────

    def get_status(self) -> list:
        columns = self.store.get_columns()
        col_map = {c["id"]: c for c in columns}
        result = []
        for col_id, integration in self._integrations.items():
            col = col_map.get(col_id, {})
            result.append({
                "column_id": col_id,
                "column_name": integration.column_name,
                "type": integration.SOURCE,
                "mode": integration.mode,
                "last_synced_at": col.get("last_synced_at"),
                "status": col.get("integration_status", "active"),
                "poll_active": col_id in self._poll_tasks,
            })
        return result

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _activate(self, column_id: int, col: dict):
        """Instantiate adapter and optionally start polling loop."""
        integration = self._build_integration(column_id, col)
        if not integration:
            return

        self._integrations[column_id] = integration

        if integration.mode in ("read", "read_write"):
            task = asyncio.create_task(self._polling_loop(column_id, integration))
            self._poll_tasks[column_id] = task
            logger.info(f"Polling started for column {column_id} ({integration.SOURCE}, "
                        f"interval={integration.sync_interval_ms}ms)")

    def _build_integration(self, column_id: int, col: dict):
        """Deserialize DB column fields into a concrete BaseIntegration instance."""
        int_type = col.get("integration_type")
        if not int_type:
            return None

        try:
            credentials = json.loads(col.get("integration_credentials") or "{}")
        except json.JSONDecodeError:
            credentials = {}
        try:
            filters = json.loads(col.get("integration_filters") or "{}")
        except json.JSONDecodeError:
            filters = {}

        # Inject webhook_secret into credentials so adapters have one dict to check
        if col.get("webhook_secret"):
            credentials.setdefault("webhook_secret", col["webhook_secret"])

        kwargs = dict(
            column_id=column_id,
            column_name=col.get("name", ""),
            credentials=credentials,
            filters=filters,
            mode=col.get("integration_mode", "read"),
            sync_interval_ms=col.get("sync_interval_ms", 60000),
            store=self.store,
            broadcaster=self.broadcaster,
        )

        if int_type == "github":
            if not credentials.get("token"):
                logger.warning(
                    f"Column {column_id}: GitHub integration missing required 'token' — "
                    "skipping activation. Reconfigure credentials in column settings."
                )
                return None
            from .github_integration import GitHubIntegration
            return GitHubIntegration(**kwargs)
        elif int_type == "jira":
            from .jira_integration import JiraIntegration
            return JiraIntegration(**kwargs)
        elif int_type == "linear":
            from .linear_integration import LinearIntegration
            return LinearIntegration(**kwargs)
        elif int_type == "firestore":
            from .firebase_integration import FirebaseIntegration
            return FirebaseIntegration(**kwargs)
        else:
            logger.warning(f"Unknown integration type '{int_type}' for column {column_id}")
            return None

    async def _polling_loop(self, column_id: int, integration):
        """Background polling loop for a single integration."""
        interval_s = max(integration.sync_interval_ms, 5000) / 1000.0
        while True:
            try:
                results = await integration.sync_in()
                now = datetime.now().isoformat()
                self.store.update_column_integration(
                    column_id,
                    last_synced_at=now,
                    integration_status="active",
                )
                count = len(results) if results else 0
                if count:
                    logger.info(f"Synced {count} item(s) for column {column_id}")
                await self.broadcaster({
                    "type": "integration_status",
                    "column_id": column_id,
                    "status": "active",
                    "last_synced_at": now,
                    "synced_count": count,
                })
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                logger.info(f"Polling loop cancelled for column {column_id}")
                break
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Polling error for column {column_id}: {error_msg}")
                self.store.update_column_integration(
                    column_id, integration_status="error"
                )
                await self.broadcaster({
                    "type": "integration_status",
                    "column_id": column_id,
                    "status": "error",
                    "error": error_msg,
                })
                await asyncio.sleep(30)  # backoff on error before retrying
