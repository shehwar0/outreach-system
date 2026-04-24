from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import Database


FOLLOW_UP_STAGES = {
    "initial": {"next": "followup1", "min_days": 3},
    "followup1": {"next": "followup2", "min_days": 3},
    "followup2": {"next": None, "min_days": 0},
}

FOLLOWUP1_TEMPLATES = [
    "Hi {name},\n\nJust checking in — did you get a chance to think about having a website for {business}? "
    "Many businesses {city} find that even a simple one-page site brings in new calls from Google.\n\n"
    "Happy to answer any questions or show you a quick example.\n\nBest regards,",

    "Hi {name},\n\nI wanted to follow up on my last note. "
    "A quick website for {business} could help customers {city} find you more easily online.\n\n"
    "Would it be worth a quick chat, or should I send over a sample first?\n\nBest,",

    "Hello {name},\n\nJust a quick follow-up. "
    "I have been working with a few businesses {city} on simple websites that help get more bookings.\n\n"
    "If you are curious, I can share a short example — no pressure either way.\n\nRegards,",
]

FOLLOWUP2_TEMPLATES = [
    "Hi {name},\n\nI have not heard back, so I will assume the timing is not right. "
    "Should I close this out for now, or would you like to revisit this later?\n\n"
    "Either way, I wish {business} all the best.\n\nTake care,",

    "Hello {name},\n\nThis will be my last note — I do not want to take up your time. "
    "If a website for {business} ever becomes a priority, feel free to reach out.\n\n"
    "Wishing you the best {city}.\n\nRegards,",

    "Hi {name},\n\nI will stop reaching out after this. "
    "If you ever want to explore getting a website for {business}, my inbox is open.\n\n"
    "All the best to you and your team {city}.\n\nThank you,",
]


class FollowUpEngine:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_leads_due_for_followup1(self, min_days: int = 3) -> List[Dict[str, Any]]:
        return self._db.get_leads_due_for_followup("initial", min_days)

    def get_leads_due_for_followup2(self, min_days: int = 3) -> List[Dict[str, Any]]:
        return self._db.get_leads_due_for_followup("followup1", min_days)

    def get_next_stage(self, current_stage: str) -> Optional[str]:
        info = FOLLOW_UP_STAGES.get(current_stage)
        if not info:
            return None
        return info["next"]

    def should_stop(self, lead_id: int) -> bool:
        lead = self._db.get_lead_by_id(lead_id)
        if not lead:
            return True

        if self._db.has_reply(lead_id):
            return True

        if self._db.is_suppressed(lead["email"]):
            return True

        return False

    def get_followup_templates(self, stage: str) -> List[str]:
        if stage == "followup1":
            return list(FOLLOWUP1_TEMPLATES)
        elif stage == "followup2":
            return list(FOLLOWUP2_TEMPLATES)
        return []

    def get_all_due_followups(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "followup1": self.get_leads_due_for_followup1(),
            "followup2": self.get_leads_due_for_followup2(),
        }
