"""
integrations/base.py
Abstract base class for all external service integrations in Aegis.

Each integration is bound to a single Kanban column and has a mode:
  "read"       — pull items from external service → Aegis cards
  "write"      — push Aegis card changes → external service
  "read_write" — bidirectional
"""
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Optional


class BaseIntegration(ABC):
    """
    Contract every integration adapter must satisfy.

    column_id:        The Aegis column this integration is bound to.
    column_name:      The column's display name (used when creating cards).
    credentials:      Dict of service-specific auth values (token, api_key, etc.).
    filters:          Dict of optional filtering params (labels, project_key, etc.).
    mode:             "read", "write", or "read_write".
    sync_interval_ms: How often (in ms) to poll when webhooks are unavailable.
    store:            AegisStore (or FirestoreStore) instance.
    broadcaster:      manager.broadcast async callable.
    """

    SOURCE: str = "unknown"  # Override in each subclass

    def __init__(
        self,
        column_id: int,
        column_name: str,
        credentials: dict,
        filters: dict,
        mode: str,
        sync_interval_ms: int,
        store,
        broadcaster,
    ):
        self.column_id = column_id
        self.column_name = column_name
        self.credentials = credentials
        self.filters = filters
        self.mode = mode
        self.sync_interval_ms = sync_interval_ms
        self.store = store
        self.broadcaster = broadcaster
        self.logger = logging.getLogger(f"aegis.integrations.{self.__class__.__name__}")

    # ── Inbound (external → Aegis) ──────────────────────────────────────────

    @abstractmethod
    async def sync_in(self) -> list:
        """
        Pull items from external source and upsert as Aegis cards.
        Must call _upsert_card() for each item.
        Returns list of cards that were created or updated.
        """
        ...

    # ── Outbound (Aegis → external) ─────────────────────────────────────────

    @abstractmethod
    async def sync_out(self, card: dict, event_type: str) -> bool:
        """
        Push an Aegis card change to the external service.
        event_type: "card_updated", "card_moved", "comment_added"
        Returns True on success.
        """
        ...

    # ── Webhook ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def handle_webhook(self, payload: dict, headers: dict) -> Optional[dict]:
        """
        Process an inbound webhook payload.
        Verify signature, parse event, upsert card.
        Returns upserted/updated card dict or None if event was ignored.
        """
        ...

    async def register_webhook(self, webhook_url: str) -> bool:
        """
        Register a webhook with the external service pointing at webhook_url.
        Override in integrations that support programmatic registration.
        Default: no-op (returns False to signal manual setup required).
        """
        return False

    async def deregister_webhook(self) -> bool:
        """Remove the webhook from the external service. Default: no-op."""
        return False

    # ── Shared helpers ───────────────────────────────────────────────────────

    async def _upsert_card(
        self,
        external_id: str,
        external_source: str,
        external_url: str,
        title: str,
        description: str,
        priority: str = "normal",
        metadata: Optional[str] = None,
    ) -> dict:
        """
        Deduplication-aware card upsert.
        Finds existing card with same (external_id, external_source).
        Creates if not found; updates title/description/metadata if they changed.
        Skips update if incoming description hash matches last_synced_hash (loop guard).
        Broadcasts card_created or card_updated via self.broadcaster.
        """
        existing = self.store.find_card_by_external_id(external_id, external_source)

        if existing:
            # Loop guard: skip if this content is an echo of our last sync_out
            incoming_hash = hashlib.sha256((description or "").encode()).hexdigest()
            if existing.get("last_synced_hash") and existing["last_synced_hash"] == incoming_hash:
                return existing

            updates = {}
            if existing.get("title") != title:
                updates["title"] = title
            if existing.get("description") != description:
                updates["description"] = description
            if metadata is not None:
                updates["metadata"] = metadata
            if updates:
                card = self.store.update_card(existing["id"], **updates)
                await self.broadcaster({"type": "card_updated", "card": card})
                return card
            return existing
        else:
            card = self.store.create_card(
                title=title,
                description=description,
                column=self.column_name,
                assignee=None,
                priority=priority,
                external_id=external_id,
                external_source=external_source,
                external_url=external_url,
                metadata=metadata,
            )
            await self.broadcaster({"type": "card_created", "card": card})
            return card

    def _map_priority(self, raw_priority: str) -> str:
        """
        Normalize external priority strings to Aegis values: high / normal / low.
        Override per integration if needed.
        """
        raw = (raw_priority or "").lower()
        if raw in ("urgent", "critical", "p0", "p1", "high", "highest", "blocker"):
            return "high"
        if raw in ("p3", "p4", "low", "lowest", "minor", "trivial"):
            return "low"
        return "normal"
