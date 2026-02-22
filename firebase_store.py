"""
Aegis Firebase Store — Cloud-backed Firestore persistence.
Drop-in replacement for the SQLite AegisStore when firebase is enabled.
"""

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("aegis.firebase")

# Conditional import — only loaded when Firebase is enabled
_firestore_client = None


def _get_db():
    """Lazy-initializes the Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not firebase_admin._apps:
                # Try to load credentials from config
                from main import CONFIG
                fb_config = CONFIG.get("fire_base", {})
                cred_path = fb_config.get("credentials_path", "")
                project_id = fb_config.get("project_id", "")

                if cred_path:
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred, {"projectId": project_id})
                else:
                    # Default credentials (e.g., GOOGLE_APPLICATION_CREDENTIALS env)
                    firebase_admin.initialize_app()

            _firestore_client = firestore.client()
            logger.info("Firebase Firestore client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            raise

    return _firestore_client


class FirestoreStore:
    """
    Cloud-backed store using Firestore.
    Mirrors the AegisStore interface for seamless swapping.
    """

    COLLECTION = "cards"

    def create_card(self, title: str, description: str = "", column: str = "Inbox",
                    assignee: Optional[str] = None) -> dict:
        db = _get_db()
        now = datetime.now().isoformat()
        card_data = {
            "title": title,
            "description": description,
            "column": column,
            "assignee": assignee,
            "created_at": now,
            "updated_at": now,
            "status": "idle",
            "logs": [],
            "comments": []
        }
        _, doc_ref = db.collection(self.COLLECTION).add(card_data)
        card_data["id"] = doc_ref.id
        return card_data

    def update_card(self, card_id, **kwargs) -> Optional[dict]:
        db = _get_db()
        if not kwargs:
            return self.get_card(card_id)

        kwargs["updated_at"] = datetime.now().isoformat()
        doc_ref = db.collection(self.COLLECTION).document(str(card_id))
        doc = doc_ref.get()
        if not doc.exists:
            return None

        doc_ref.update(kwargs)
        return self.get_card(card_id)

    def get_card(self, card_id) -> Optional[dict]:
        db = _get_db()
        doc = db.collection(self.COLLECTION).document(str(card_id)).get()
        if not doc.exists:
            return None
        card = doc.to_dict()
        card["id"] = doc.id
        # Ensure list fields
        if isinstance(card.get("logs"), str):
            card["logs"] = json.loads(card["logs"])
        if isinstance(card.get("comments"), str):
            card["comments"] = json.loads(card["comments"])
        return card

    def get_cards(self, column: Optional[str] = None) -> list:
        db = _get_db()
        query = db.collection(self.COLLECTION)
        if column:
            query = query.where("column", "==", column)

        cards = []
        for doc in query.stream():
            card = doc.to_dict()
            card["id"] = doc.id
            if isinstance(card.get("logs"), str):
                card["logs"] = json.loads(card["logs"])
            if isinstance(card.get("comments"), str):
                card["comments"] = json.loads(card["comments"])
            cards.append(card)
        return cards

    def delete_card(self, card_id) -> bool:
        db = _get_db()
        doc_ref = db.collection(self.COLLECTION).document(str(card_id))
        doc = doc_ref.get()
        if doc.exists:
            doc_ref.delete()
            return True
        return False
