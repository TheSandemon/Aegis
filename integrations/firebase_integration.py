"""
integrations/firebase_integration.py
Firebase Firestore adapter for Aegis — polling only (no native webhook support via REST).

Uses the Firestore REST API (no SDK required).

Credentials:
  api_key      — Firebase Web API key (from Firebase project settings > General > Web API Key)
  project_id   — Firebase project ID
  collection   — Firestore collection name (default: "tasks")

Expected document field names:
  title        — (string) card title
  description  — (string, optional) card description
  priority     — (string, optional) "high" | "normal" | "low"
  status       — (string, optional) current status; updated on sync_out

Documents are linked to Aegis cards by their Firestore document ID (external_id).
"""
from typing import Optional

import httpx

from .base import BaseIntegration

_FIRESTORE_BASE = "https://firestore.googleapis.com/v1"


def _extract_field(field_val: dict) -> str:
    """Extract a plain string from a Firestore field value wrapper."""
    for key in ("stringValue", "integerValue", "booleanValue", "doubleValue"):
        if key in field_val:
            return str(field_val[key])
    return ""


def _string_value(val: str) -> dict:
    return {"stringValue": val}


class FirebaseIntegration(BaseIntegration):
    SOURCE = "firestore"

    def _project(self) -> str:
        return self.credentials.get("project_id", "")

    def _collection(self) -> str:
        return self.credentials.get("collection", "tasks")

    def _api_key(self) -> str:
        return self.credentials.get("api_key", "")

    def _collection_url(self) -> str:
        return (
            f"{_FIRESTORE_BASE}/projects/{self._project()}"
            f"/databases/(default)/documents/{self._collection()}"
            f"?key={self._api_key()}"
        )

    def _doc_url(self, doc_id: str) -> str:
        return (
            f"{_FIRESTORE_BASE}/projects/{self._project()}"
            f"/databases/(default)/documents/{self._collection()}/{doc_id}"
            f"?key={self._api_key()}"
        )

    def _console_url(self, doc_id: str) -> str:
        return (
            f"https://console.firebase.google.com/project/{self._project()}"
            f"/firestore/data/{self._collection()}/{doc_id}"
        )

    # ── sync_in ──────────────────────────────────────────────────────────────

    async def sync_in(self) -> list:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._collection_url())
            resp.raise_for_status()
            data = resp.json()

        results = []
        for doc in data.get("documents", []):
            fields = doc.get("fields", {})
            # The document name is a full resource path; last segment is the doc ID
            doc_id = doc["name"].split("/")[-1]

            title = _extract_field(fields.get("title", {})) or f"Firestore: {doc_id}"
            description = _extract_field(fields.get("description", {}))
            priority_raw = _extract_field(fields.get("priority", {}))

            card = await self._upsert_card(
                external_id=doc_id,
                external_source=self.SOURCE,
                external_url=self._console_url(doc_id),
                title=title,
                description=description,
                priority=self._map_priority(priority_raw),
            )
            results.append(card)
        return results

    # ── sync_out ─────────────────────────────────────────────────────────────

    async def sync_out(self, card: dict, event_type: str) -> bool:
        if card.get("external_source") != self.SOURCE:
            return False
        doc_id = card.get("external_id")
        if not doc_id:
            return False

        # Map Aegis card state to a Firestore status string
        if event_type == "card_moved":
            col = card.get("column", "")
            fs_status_map = {
                "Done": "done",
                "In Progress": "in_progress",
                "Blocked": "blocked",
                "Review": "review",
            }
            fs_status = fs_status_map.get(col, col.lower().replace(" ", "_"))
        else:
            fs_status = card.get("status", "idle")

        # Firestore PATCH with updateMask so we only touch the status field
        url = (
            f"{_FIRESTORE_BASE}/projects/{self._project()}"
            f"/databases/(default)/documents/{self._collection()}/{doc_id}"
            f"?updateMask.fieldPaths=status&key={self._api_key()}"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.patch(
                url,
                json={"fields": {"status": _string_value(fs_status)}},
            )
            return resp.status_code == 200

    # ── handle_webhook ───────────────────────────────────────────────────────

    async def handle_webhook(self, payload: dict, headers: dict) -> Optional[dict]:
        # Firestore REST API does not support inbound webhooks.
        # This adapter is polling-only; this method should never be called.
        self.logger.warning("Firebase adapter received webhook — ignoring (polling-only adapter)")
        return None

    async def register_webhook(self, webhook_url: str) -> bool:
        return False  # Polling only; no webhook support
