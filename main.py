from __future__ import annotations

import argparse
import csv
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus

from config import AppConfig, export_default_config, load_config
from database import Database
from distributor import SenderDistributor
from email_sender import EmailDeliveryError, EmailSender
from follow_up_engine import FollowUpEngine
from lead_scorer import score_and_segment_lead
from logger import OutreachLogRecord, OutreachLogger
from personalization import PersonalizationEngine
from template_manager import TemplateManager


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Lead:
    name: str
    email: str
    business: str
    city: str
    category: str = ""
    phone: str = ""
    website_exists: bool = False
    reviews_count: int = 0
    social_presence: str = ""
    lead_score: int = 0
    segment: str = "low"
    niche: str = ""
    db_id: int = 0


@dataclass
class CampaignRunStats:
    total_leads: int = 0
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    skipped_duplicates: int = 0
    current_recipient: str = ""
    started_at: str = ""
    finished_at: str = ""
    stopped_by_user: bool = False
    summary: str = ""
    campaign_type: str = "initial"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automated cold email outreach system")
    parser.add_argument("--config", default="config.json", help="Path to JSON config file")
    parser.add_argument("--leads", default=None, help="Path to leads CSV (overrides config)")
    parser.add_argument("--dry-run", action="store_true", help="Do not send emails, only log attempts")
    return parser.parse_args()


def read_leads(csv_path: str) -> List[Lead]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Leads CSV file not found: {csv_path}")

    leads: List[Lead] = []
    seen_emails = set()

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError("Leads CSV is empty or missing headers.")

        normalized_headers = {h.strip().lower() for h in reader.fieldnames if h}
        required_headers = {"name", "email", "business"}
        if not required_headers.issubset(normalized_headers):
            raise ValueError("CSV must include headers: name, email, business (city optional).")

        for row in reader:
            lowered_row = {str(key).strip().lower(): value for key, value in row.items()}

            email = _normalize_text(lowered_row.get("email", "")).lower()
            if not email or not EMAIL_PATTERN.match(email):
                continue

            if email in seen_emails:
                continue
            seen_emails.add(email)

            name = _normalize_text(lowered_row.get("name", "")) or "there"
            business = _normalize_text(lowered_row.get("business", "")) or "business"
            city = _normalize_text(lowered_row.get("city", ""))
            category = _normalize_text(lowered_row.get("category", ""))
            phone = _normalize_text(lowered_row.get("phone", ""))

            website_exists_raw = _normalize_text(lowered_row.get("website_exists", "")).lower()
            website_exists = website_exists_raw in {"true", "1", "yes"}

            reviews_count = 0
            reviews_raw = _normalize_text(lowered_row.get("reviews_count", lowered_row.get("reviews", "")))
            if reviews_raw.isdigit():
                reviews_count = int(reviews_raw)

            social_presence = _normalize_text(lowered_row.get("social_presence", ""))

            lead_data = {
                "name": name,
                "email": email,
                "business": business,
                "city": city,
                "category": category,
                "phone": phone,
                "website_exists": website_exists,
                "reviews_count": reviews_count,
                "social_presence": social_presence,
            }
            scored = score_and_segment_lead(lead_data)

            leads.append(Lead(
                name=name,
                email=email,
                business=business,
                city=city,
                category=category,
                phone=phone,
                website_exists=website_exists,
                reviews_count=reviews_count,
                social_presence=social_presence,
                lead_score=scored["lead_score"],
                segment=scored["segment"],
                niche=scored.get("niche", ""),
            ))

    return leads


def import_leads_to_db(leads: List[Lead], db: Database) -> int:
    imported = 0
    for lead in leads:
        existing = db.get_lead_by_email(lead.email)
        if not existing:
            db.insert_lead({
                "name": lead.name,
                "email": lead.email,
                "business": lead.business,
                "category": lead.category,
                "city": lead.city,
                "phone": lead.phone,
                "website_exists": lead.website_exists,
                "social_presence": lead.social_presence,
                "reviews_count": lead.reviews_count,
                "lead_score": lead.lead_score,
                "segment": lead.segment,
                "niche": lead.niche,
                "source": "csv",
            })
            imported += 1
        else:
            lead.db_id = existing["id"]
    return imported


def generate_demo_link(config: AppConfig, lead: Lead) -> str:
    if not config.demo_base_url:
        return ""
    base = config.demo_base_url.rstrip("/")
    params = f"?company={quote_plus(lead.business)}&city={quote_plus(lead.city)}"
    return f"{base}{params}"


def build_placeholders(lead: Lead, context_line: str, demo_link: str = "", config: Optional[AppConfig] = None) -> Dict[str, str]:
    physical_address = config.physical_address if config else "Islamabad, Pakistan"
    unsubscribe_line = config.unsubscribe_text.replace("{physical_address}", physical_address) if config else ""

    return {
        "name": lead.name,
        "business": lead.business,
        "city": f"in {lead.city}" if lead.city else "",
        "context_line": context_line,
        "demo_link": demo_link,
        "physical_address": physical_address,
        "unsubscribe_text": unsubscribe_line,
    }


def append_compliance_footer(body: str, config: AppConfig) -> str:
    footer = config.unsubscribe_text.replace("{physical_address}", config.physical_address)
    return f"{body}\n\n---\n{footer}"


def run_campaign(
    config: AppConfig,
    stop_requested: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[CampaignRunStats], None]] = None,
    campaign_type: str = "initial",
) -> CampaignRunStats:
    campaign_logger = OutreachLogger(
        csv_path=config.logs_csv_path,
        jsonl_path=config.logs_jsonl_path,
        sent_recipients_path=config.sent_recipients_path,
    )

    db = Database()
    db.seed_default_canned_responses()

    stats = CampaignRunStats(
        started_at=datetime.now(timezone.utc).isoformat(),
        campaign_type=campaign_type,
    )

    sent_recipients = campaign_logger.load_sent_recipients_from_history()
    campaign_logger.console.info("Loaded %s already-sent recipients.", len(sent_recipients))

    # Determine leads based on campaign type
    if campaign_type == "initial":
        leads = read_leads(config.leads_csv_path)
        import_leads_to_db(leads, db)
    elif campaign_type == "followup1":
        follow_engine = FollowUpEngine(db)
        due_leads_data = follow_engine.get_leads_due_for_followup1(config.follow_up_day_1)
        leads = [_db_row_to_lead(row) for row in due_leads_data]
    elif campaign_type == "followup2":
        follow_engine = FollowUpEngine(db)
        due_leads_data = follow_engine.get_leads_due_for_followup2(config.follow_up_day_2)
        leads = [_db_row_to_lead(row) for row in due_leads_data]
    else:
        leads = read_leads(config.leads_csv_path)
        import_leads_to_db(leads, db)

    stats.total_leads = len(leads)
    if not leads:
        msg = f"No leads found for {campaign_type} campaign."
        campaign_logger.console.info(msg)
        stats.finished_at = datetime.now(timezone.utc).isoformat()
        stats.summary = msg
        _emit_progress(progress_callback, stats)
        return stats

    today = date.today()
    already_sent_today = campaign_logger.count_sent_for_date(today)
    remaining_daily_global = max(0, config.total_daily_limit - already_sent_today)
    if remaining_daily_global <= 0:
        campaign_logger.console.info("Global daily limit reached for today (%s).", config.total_daily_limit)
        stats.finished_at = datetime.now(timezone.utc).isoformat()
        stats.summary = f"Global daily limit reached for today ({config.total_daily_limit})."
        _emit_progress(progress_callback, stats)
        return stats

    distributor = SenderDistributor(config.senders, config.sender_type_priority)
    distributor.apply_existing_counts(campaign_logger.load_sender_attempt_counts_for_date(today))

    personalization_engine = PersonalizationEngine(config.ai)

    # Pick correct templates based on campaign type
    if campaign_type == "followup1":
        from follow_up_engine import FOLLOWUP1_TEMPLATES
        body_templates = FOLLOWUP1_TEMPLATES
    elif campaign_type == "followup2":
        from follow_up_engine import FOLLOWUP2_TEMPLATES
        body_templates = FOLLOWUP2_TEMPLATES
    else:
        body_templates = config.body_templates

    template_manager = TemplateManager(config.subject_templates, body_templates)
    email_sender = EmailSender(dry_run=config.dry_run)

    campaign_id = db.create_campaign(
        name=f"{campaign_type}_{datetime.now().strftime('%Y%m%d_%H%M')}",
        campaign_type=campaign_type,
    )

    randomizer = random.Random()
    campaign_logger.console.info("Starting %s outreach with %s leads.", campaign_type, len(leads))
    campaign_logger.console.info("Dry run mode: %s", config.dry_run)
    _emit_progress(progress_callback, stats)

    follow_up_stage = "initial" if campaign_type == "initial" else campaign_type

    try:
        for index, lead in enumerate(leads):
            if _should_stop(stop_requested):
                stats.stopped_by_user = True
                campaign_logger.console.warning("Stop requested. Ending run safely.")
                break

            if stats.sent >= remaining_daily_global:
                campaign_logger.console.info("Reached global daily cap for this run.")
                break

            # Skip if suppressed
            if db.is_suppressed(lead.email):
                stats.skipped_duplicates += 1
                _emit_progress(progress_callback, stats)
                continue

            # For initial campaign, skip already-sent
            if campaign_type == "initial" and campaign_logger.already_sent(lead.email):
                stats.skipped_duplicates += 1
                _emit_progress(progress_callback, stats)
                continue

            stats.current_recipient = lead.email
            sender = distributor.pick_sender()
            if not sender:
                campaign_logger.console.info("No sender has remaining quota. Stopping run.")
                break

            context_line = personalization_engine.generate_context_line(
                name=lead.name,
                business=lead.business,
                city=lead.city,
            )
            demo_link = generate_demo_link(config, lead) if lead.segment == "high" else ""
            placeholders = build_placeholders(lead=lead, context_line=context_line, demo_link=demo_link, config=config)

            subject_template = template_manager.pick_subject_template()
            body_template = template_manager.pick_body_template()
            subject = template_manager.render(subject_template, placeholders)
            body = template_manager.render(body_template, placeholders)
            body = append_compliance_footer(body, config)

            # Get template variant indices
            template_variant = body_templates.index(body_template) if body_template in body_templates else 0
            subject_variant = config.subject_templates.index(subject_template) if subject_template in config.subject_templates else 0

            error_message = ""
            status = "failed"
            try:
                email_sender.send_email(
                    sender=sender,
                    recipient_email=lead.email,
                    subject=subject,
                    body=body,
                )
                status = "sent"
                stats.sent += 1
                campaign_logger.mark_sent(lead.email)
            except EmailDeliveryError as exc:
                error_message = str(exc)
                stats.failed += 1

            stats.attempted += 1

            # Log to CSV/JSONL (legacy)
            campaign_logger.log_event(
                OutreachLogRecord(
                    recipient_email=lead.email,
                    sender_email=sender.email,
                    sender_type=sender.type,
                    subject=subject,
                    status=status,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    error=error_message,
                )
            )

            # Log to database
            lead_db = db.get_lead_by_email(lead.email)
            if lead_db:
                db.log_send({
                    "lead_id": lead_db["id"],
                    "campaign_id": campaign_id,
                    "sender_email": sender.email,
                    "sender_type": sender.type,
                    "subject": subject,
                    "body": body,
                    "template_variant": template_variant,
                    "subject_variant": subject_variant,
                    "status": status,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "follow_up_stage": follow_up_stage,
                    "demo_link_included": bool(demo_link),
                    "error_message": error_message,
                })
                if status == "sent" and lead_db["funnel_stage"] == "new":
                    db.update_lead(lead_db["id"], {"funnel_stage": "contacted"})

            _emit_progress(progress_callback, stats)

            if config.dry_run:
                continue
            if index >= len(leads) - 1:
                continue
            if stats.sent >= remaining_daily_global:
                continue
            if not distributor.has_capacity():
                continue

            delay_seconds = randomizer.randint(config.delay_min_seconds, config.delay_max_seconds)
            campaign_logger.console.info("Sleeping for %s seconds before next send.", delay_seconds)
            if _sleep_with_stop(delay_seconds, stop_requested):
                stats.stopped_by_user = True
                campaign_logger.console.warning("Stop requested during delay. Ending run safely.")
                break

    except KeyboardInterrupt:
        stats.stopped_by_user = True
        campaign_logger.console.warning("Interrupted by user. Progress saved; next run will resume.")

    stats.finished_at = datetime.now(timezone.utc).isoformat()
    stats.summary = (
        f"Run complete ({campaign_type}). attempted={stats.attempted} sent={stats.sent} "
        f"failed={stats.failed} skipped_duplicates={stats.skipped_duplicates}"
    )

    db.finish_campaign(campaign_id, "stopped" if stats.stopped_by_user else "completed")

    campaign_logger.console.info(
        "Run complete. attempted=%s sent=%s failed=%s skipped_duplicates=%s",
        stats.attempted,
        stats.sent,
        stats.failed,
        stats.skipped_duplicates,
    )
    _emit_progress(progress_callback, stats)
    return stats


def _db_row_to_lead(row: Dict) -> Lead:
    return Lead(
        name=row.get("name", "there"),
        email=row["email"],
        business=row.get("business", ""),
        city=row.get("city", ""),
        category=row.get("category", ""),
        phone=row.get("phone", ""),
        website_exists=bool(row.get("website_exists", 0)),
        reviews_count=int(row.get("reviews_count", 0)),
        social_presence=row.get("social_presence", ""),
        lead_score=int(row.get("lead_score", 0)),
        segment=row.get("segment", "low"),
        niche=row.get("niche", ""),
        db_id=int(row.get("id", 0)),
    )


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _should_stop(stop_requested: Optional[Callable[[], bool]]) -> bool:
    if not stop_requested:
        return False
    try:
        return bool(stop_requested())
    except Exception:
        return False


def _sleep_with_stop(seconds: int, stop_requested: Optional[Callable[[], bool]]) -> bool:
    for _ in range(max(0, seconds)):
        if _should_stop(stop_requested):
            return True
        time.sleep(1)
    return False


def _emit_progress(
    progress_callback: Optional[Callable[[CampaignRunStats], None]],
    stats: CampaignRunStats,
) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(stats)
    except Exception:
        return


def main() -> None:
    export_default_config()

    args = parse_args()
    config = load_config(args.config)
    if args.leads:
        config.leads_csv_path = args.leads
    if args.dry_run:
        config.dry_run = True

    config.validate()
    run_campaign(config)


if __name__ == "__main__":
    main()
