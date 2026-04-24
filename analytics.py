from __future__ import annotations

from typing import Any, Dict, List

from database import Database


class Analytics:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_kpis(self) -> Dict[str, Any]:
        total_sent = self._db.get_total_sent()
        total_failed = self._db.get_total_failed()
        total_replies = self._db.get_total_replies()
        positive_replies = self._db.get_positive_replies()
        meetings = self._db.get_meetings_booked()
        deals_won = self._db.get_deals_won()
        deals_lost = self._db.get_deals_lost()
        total_leads = self._db.get_lead_count()

        delivery_rate = round((total_sent / (total_sent + total_failed) * 100), 1) if (total_sent + total_failed) > 0 else 0
        reply_rate = round((total_replies / total_sent * 100), 1) if total_sent > 0 else 0
        positive_rate = round((positive_replies / total_sent * 100), 1) if total_sent > 0 else 0
        meeting_rate = round((meetings / total_sent * 100), 1) if total_sent > 0 else 0
        close_rate = round((deals_won / total_sent * 100), 1) if total_sent > 0 else 0

        return {
            "total_leads": total_leads,
            "total_sent": total_sent,
            "total_failed": total_failed,
            "total_replies": total_replies,
            "positive_replies": positive_replies,
            "meetings_booked": meetings,
            "deals_won": deals_won,
            "deals_lost": deals_lost,
            "delivery_rate": delivery_rate,
            "reply_rate": reply_rate,
            "positive_reply_rate": positive_rate,
            "meeting_rate": meeting_rate,
            "close_rate": close_rate,
        }

    def get_funnel_data(self) -> Dict[str, int]:
        return self._db.get_funnel_counts()

    def get_template_performance(self) -> List[Dict[str, Any]]:
        return self._db.get_template_performance()

    def get_daily_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        return self._db.get_daily_stats(days)

    def get_today_sent(self) -> int:
        return self._db.count_sends_today()
