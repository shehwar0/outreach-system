from __future__ import annotations

from typing import Any, Dict, List, Optional

from database import Database


class ReplyManager:
    REPLY_TYPES = [
        "positive",
        "how_much",
        "not_now",
        "send_details",
        "negative",
        "wrong_contact",
        "unsubscribe",
        "unclassified",
    ]

    def __init__(self, db: Database) -> None:
        self._db = db

    def log_reply(
        self,
        lead_id: int,
        reply_text: str = "",
        reply_type: str = "unclassified",
        email_send_id: Optional[int] = None,
    ) -> int:
        reply_data = {
            "lead_id": lead_id,
            "email_send_id": email_send_id,
            "reply_type": reply_type,
            "reply_text_snippet": reply_text[:500] if reply_text else "",
        }
        reply_id = self._db.add_reply(reply_data)

        self._db.update_lead(lead_id, {"funnel_stage": "replied"})

        if reply_type in {"unsubscribe", "wrong_contact"}:
            lead = self._db.get_lead_by_id(lead_id)
            if lead:
                self._db.add_to_suppression(lead["email"], reason=reply_type)

        return reply_id

    def classify_reply(self, reply_id: int, reply_type: str, notes: str = "") -> None:
        if reply_type not in self.REPLY_TYPES:
            raise ValueError(f"Invalid reply type: {reply_type}")

        self._db.classify_reply(reply_id, reply_type, notes)

        all_replies = self._db.get_all_replies()
        for reply in all_replies:
            if reply["id"] == reply_id:
                lead_id = reply["lead_id"]
                if reply_type in {"unsubscribe", "wrong_contact"}:
                    lead = self._db.get_lead_by_id(lead_id)
                    if lead:
                        self._db.add_to_suppression(lead["email"], reason=reply_type)
                break

    def get_pending_replies(self) -> List[Dict[str, Any]]:
        return self._db.get_all_replies(handled=False)

    def get_all_replies(self) -> List[Dict[str, Any]]:
        return self._db.get_all_replies()

    def get_canned_response(self, trigger_type: str) -> Optional[str]:
        responses = self._db.get_canned_responses()
        for r in responses:
            if r["trigger_type"] == trigger_type:
                return r["response_text"]
        return None

    def get_canned_responses(self) -> List[Dict[str, Any]]:
        return self._db.get_canned_responses()
