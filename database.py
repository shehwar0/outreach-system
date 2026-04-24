from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


DB_PATH = Path(__file__).resolve().parent / "data" / "outreach.db"


class Database:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = Path(db_path) if db_path else DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL DEFAULT 'there',
                    email TEXT NOT NULL UNIQUE,
                    business TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    website_exists INTEGER NOT NULL DEFAULT 0,
                    social_presence TEXT NOT NULL DEFAULT '',
                    reviews_count INTEGER NOT NULL DEFAULT 0,
                    lead_score INTEGER NOT NULL DEFAULT 0,
                    segment TEXT NOT NULL DEFAULT 'low',
                    source TEXT NOT NULL DEFAULT 'csv',
                    niche TEXT NOT NULL DEFAULT '',
                    funnel_stage TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    campaign_type TEXT NOT NULL DEFAULT 'initial',
                    status TEXT NOT NULL DEFAULT 'created',
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS email_sends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id INTEGER NOT NULL,
                    campaign_id INTEGER,
                    sender_email TEXT NOT NULL,
                    sender_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    template_variant INTEGER NOT NULL DEFAULT 0,
                    subject_variant INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    sent_at TEXT NOT NULL,
                    follow_up_stage TEXT NOT NULL DEFAULT 'initial',
                    demo_link_included INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (lead_id) REFERENCES leads(id)
                );

                CREATE TABLE IF NOT EXISTS replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id INTEGER NOT NULL,
                    email_send_id INTEGER,
                    reply_type TEXT NOT NULL DEFAULT 'unclassified',
                    reply_text_snippet TEXT NOT NULL DEFAULT '',
                    replied_at TEXT NOT NULL,
                    handled INTEGER NOT NULL DEFAULT 0,
                    handler_notes TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (lead_id) REFERENCES leads(id)
                );

                CREATE TABLE IF NOT EXISTS funnel_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    lost_reason TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (lead_id) REFERENCES leads(id)
                );

                CREATE TABLE IF NOT EXISTS suppression_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    reason TEXT NOT NULL DEFAULT 'unsubscribed',
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS canned_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_type TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    response_text TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
                CREATE INDEX IF NOT EXISTS idx_leads_segment ON leads(segment);
                CREATE INDEX IF NOT EXISTS idx_leads_funnel ON leads(funnel_stage);
                CREATE INDEX IF NOT EXISTS idx_sends_lead ON email_sends(lead_id);
                CREATE INDEX IF NOT EXISTS idx_sends_stage ON email_sends(follow_up_stage);
                CREATE INDEX IF NOT EXISTS idx_sends_status ON email_sends(status);
                CREATE INDEX IF NOT EXISTS idx_replies_lead ON replies(lead_id);
                CREATE INDEX IF NOT EXISTS idx_suppression_email ON suppression_list(email);
            """)

    # ── Leads ──────────────────────────────────────────────────────────

    def insert_lead(self, lead: Dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO leads
                    (name, email, business, category, city, phone,
                     website_exists, social_presence, reviews_count,
                     lead_score, segment, source, niche, funnel_stage, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
            """, (
                lead.get("name", "there"),
                lead["email"].strip().lower(),
                lead.get("business", ""),
                lead.get("category", ""),
                lead.get("city", ""),
                lead.get("phone", ""),
                1 if lead.get("website_exists") else 0,
                lead.get("social_presence", ""),
                int(lead.get("reviews_count", 0)),
                int(lead.get("lead_score", 0)),
                lead.get("segment", "low"),
                lead.get("source", "csv"),
                lead.get("niche", ""),
                now,
            ))
            return cur.lastrowid or 0

    def get_all_leads(self, segment: Optional[str] = None, funnel_stage: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM leads WHERE 1=1"
        params: List[Any] = []
        if segment:
            query += " AND segment = ?"
            params.append(segment)
        if funnel_stage:
            query += " AND funnel_stage = ?"
            params.append(funnel_stage)
        query += " ORDER BY lead_score DESC, id ASC"
        with self._cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_lead_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM leads WHERE email = ?", (email.strip().lower(),))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_lead_by_id(self, lead_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def update_lead(self, lead_id: int, updates: Dict[str, Any]) -> None:
        if not updates:
            return
        set_parts = [f"{key} = ?" for key in updates]
        values = list(updates.values()) + [lead_id]
        with self._cursor() as cur:
            cur.execute(f"UPDATE leads SET {', '.join(set_parts)} WHERE id = ?", values)

    def get_lead_count(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM leads")
            return cur.fetchone()[0]

    # ── Campaigns ─────────────────────────────────────────────────────

    def create_campaign(self, name: str, campaign_type: str = "initial") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO campaigns (name, campaign_type, status, created_at) VALUES (?, ?, 'running', ?)",
                (name, campaign_type, now),
            )
            return cur.lastrowid or 0

    def finish_campaign(self, campaign_id: int, status: str = "completed") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE campaigns SET status = ?, finished_at = ? WHERE id = ?",
                (status, now, campaign_id),
            )

    def get_campaigns(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM campaigns ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # ── Email Sends ───────────────────────────────────────────────────

    def log_send(self, send: Dict[str, Any]) -> int:
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO email_sends
                    (lead_id, campaign_id, sender_email, sender_type,
                     subject, body, template_variant, subject_variant,
                     status, sent_at, follow_up_stage, demo_link_included, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                send["lead_id"],
                send.get("campaign_id"),
                send["sender_email"],
                send["sender_type"],
                send["subject"],
                send.get("body", ""),
                send.get("template_variant", 0),
                send.get("subject_variant", 0),
                send["status"],
                send["sent_at"],
                send.get("follow_up_stage", "initial"),
                1 if send.get("demo_link_included") else 0,
                send.get("error_message", ""),
            ))
            return cur.lastrowid or 0

    def get_sends_for_lead(self, lead_id: int) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM email_sends WHERE lead_id = ? ORDER BY sent_at ASC",
                (lead_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_last_send_for_lead(self, lead_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM email_sends WHERE lead_id = ? AND status = 'sent' ORDER BY sent_at DESC LIMIT 1",
                (lead_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_recent_sends(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT es.*, l.name as lead_name, l.business as lead_business
                FROM email_sends es
                LEFT JOIN leads l ON es.lead_id = l.id
                ORDER BY es.sent_at DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def count_sends_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM email_sends WHERE status = 'sent' AND sent_at LIKE ?",
                (f"{today}%",),
            )
            return cur.fetchone()[0]

    def get_send_counts_by_sender_today(self) -> Dict[str, int]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._cursor() as cur:
            cur.execute("""
                SELECT sender_email, COUNT(*) as cnt
                FROM email_sends
                WHERE sent_at LIKE ? AND status IN ('sent', 'failed')
                GROUP BY sender_email
            """, (f"{today}%",))
            return {row["sender_email"]: row["cnt"] for row in cur.fetchall()}

    # ── Replies ───────────────────────────────────────────────────────

    def add_reply(self, reply: Dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO replies
                    (lead_id, email_send_id, reply_type, reply_text_snippet, replied_at, handled, handler_notes)
                VALUES (?, ?, ?, ?, ?, 0, '')
            """, (
                reply["lead_id"],
                reply.get("email_send_id"),
                reply.get("reply_type", "unclassified"),
                reply.get("reply_text_snippet", ""),
                reply.get("replied_at", now),
            ))
            return cur.lastrowid or 0

    def classify_reply(self, reply_id: int, reply_type: str, notes: str = "") -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE replies SET reply_type = ?, handled = 1, handler_notes = ? WHERE id = ?",
                (reply_type, notes, reply_id),
            )

    def get_all_replies(self, handled: Optional[bool] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT r.*, l.name as lead_name, l.email as lead_email, l.business as lead_business
            FROM replies r
            LEFT JOIN leads l ON r.lead_id = l.id
        """
        params: List[Any] = []
        if handled is not None:
            query += " WHERE r.handled = ?"
            params.append(1 if handled else 0)
        query += " ORDER BY r.replied_at DESC"
        with self._cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def has_reply(self, lead_id: int) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM replies WHERE lead_id = ?", (lead_id,))
            return cur.fetchone()[0] > 0

    # ── Funnel Events ─────────────────────────────────────────────────

    def add_funnel_event(self, lead_id: int, event_type: str, notes: str = "", lost_reason: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO funnel_events (lead_id, event_type, event_date, notes, lost_reason)
                VALUES (?, ?, ?, ?, ?)
            """, (lead_id, event_type, now, notes, lost_reason))

            stage_map = {
                "replied": "replied",
                "meeting_booked": "meeting",
                "meeting_completed": "meeting",
                "proposal_sent": "proposal",
                "deal_won": "won",
                "deal_lost": "lost",
            }
            new_stage = stage_map.get(event_type)
            if new_stage:
                cur.execute("UPDATE leads SET funnel_stage = ? WHERE id = ?", (new_stage, lead_id))

            return cur.lastrowid or 0

    def get_funnel_events(self, lead_id: int) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM funnel_events WHERE lead_id = ? ORDER BY event_date ASC",
                (lead_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_funnel_counts(self) -> Dict[str, int]:
        with self._cursor() as cur:
            cur.execute("SELECT funnel_stage, COUNT(*) as cnt FROM leads GROUP BY funnel_stage")
            return {row["funnel_stage"]: row["cnt"] for row in cur.fetchall()}

    # ── Suppression ───────────────────────────────────────────────────

    def add_to_suppression(self, email: str, reason: str = "unsubscribed") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO suppression_list (email, reason, added_at) VALUES (?, ?, ?)",
                (email.strip().lower(), reason, now),
            )

    def is_suppressed(self, email: str) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM suppression_list WHERE email = ?", (email.strip().lower(),))
            return cur.fetchone()[0] > 0

    def get_suppression_list(self) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM suppression_list ORDER BY added_at DESC")
            return [dict(row) for row in cur.fetchall()]

    # ── Canned Responses ──────────────────────────────────────────────

    def add_canned_response(self, trigger_type: str, title: str, response_text: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO canned_responses (trigger_type, title, response_text) VALUES (?, ?, ?)",
                (trigger_type, title, response_text),
            )
            return cur.lastrowid or 0

    def get_canned_responses(self) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM canned_responses ORDER BY trigger_type, id")
            return [dict(row) for row in cur.fetchall()]

    def delete_canned_response(self, response_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM canned_responses WHERE id = ?", (response_id,))

    def seed_default_canned_responses(self) -> None:
        existing = self.get_canned_responses()
        if existing:
            return

        defaults = [
            ("interested", "Meeting Offer",
             "Great! I can quickly show you how a site would look for your business. "
             "Would you prefer a quick 15-min call, or should I email you a detailed proposal first?"),
            ("how_much", "Pricing Reply",
             "It depends on what you need — every business is different. "
             "Could you tell me a bit more about what you have in mind? I can tailor a quote after that."),
            ("not_now", "Polite Pause",
             "No problem at all, I completely understand. "
             "Would it be okay to check back in a month or so, or should I close your file?"),
            ("send_details", "Details Offer",
             "Certainly — I can email you a one-page overview of what I can do, "
             "or I can jump on a quick call to walk you through it. Which do you prefer?"),
            ("wrong_contact", "Removal Confirmation",
             "Sorry about that, and thanks for letting me know. I have removed you from the list."),
        ]
        for trigger, title, text in defaults:
            self.add_canned_response(trigger, title, text)

    # ── Analytics Queries ─────────────────────────────────────────────

    def get_total_sent(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM email_sends WHERE status = 'sent'")
            return cur.fetchone()[0]

    def get_total_failed(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM email_sends WHERE status = 'failed'")
            return cur.fetchone()[0]

    def get_total_replies(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM replies")
            return cur.fetchone()[0]

    def get_positive_replies(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM replies WHERE reply_type = 'positive'")
            return cur.fetchone()[0]

    def get_meetings_booked(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM funnel_events WHERE event_type = 'meeting_booked'")
            return cur.fetchone()[0]

    def get_deals_won(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM funnel_events WHERE event_type = 'deal_won'")
            return cur.fetchone()[0]

    def get_deals_lost(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM funnel_events WHERE event_type = 'deal_lost'")
            return cur.fetchone()[0]

    def get_template_performance(self) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT
                    es.template_variant,
                    es.follow_up_stage,
                    COUNT(*) as total_sent,
                    SUM(CASE WHEN r.id IS NOT NULL THEN 1 ELSE 0 END) as reply_count
                FROM email_sends es
                LEFT JOIN replies r ON r.lead_id = es.lead_id
                WHERE es.status = 'sent'
                GROUP BY es.template_variant, es.follow_up_stage
                ORDER BY reply_count DESC
            """)
            return [dict(row) for row in cur.fetchall()]

    def get_daily_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT
                    DATE(sent_at) as send_date,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM email_sends
                GROUP BY DATE(sent_at)
                ORDER BY send_date DESC
                LIMIT ?
            """, (days,))
            return [dict(row) for row in cur.fetchall()]

    def get_leads_due_for_followup(self, stage: str, min_days_since_last: int) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT l.*, es.sent_at as last_sent_at, es.follow_up_stage as last_stage
                FROM leads l
                INNER JOIN email_sends es ON es.lead_id = l.id AND es.status = 'sent'
                LEFT JOIN replies r ON r.lead_id = l.id
                LEFT JOIN suppression_list sl ON sl.email = l.email
                WHERE r.id IS NULL
                  AND sl.id IS NULL
                  AND es.follow_up_stage = ?
                  AND JULIANDAY('now') - JULIANDAY(es.sent_at) >= ?
                  AND l.id NOT IN (
                      SELECT lead_id FROM email_sends
                      WHERE follow_up_stage != ? AND follow_up_stage != 'initial'
                      AND CASE WHEN ? = 'initial' THEN follow_up_stage IN ('followup1','followup2')
                           WHEN ? = 'followup1' THEN follow_up_stage = 'followup2'
                           ELSE 0 END
                  )
                GROUP BY l.id
                ORDER BY l.lead_score DESC
            """, (stage, min_days_since_last, stage, stage, stage))
            return [dict(row) for row in cur.fetchall()]
