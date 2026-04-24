from __future__ import annotations

import csv
import json
import shutil
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from analytics import Analytics
from config import DEFAULT_BODY_TEMPLATES, export_default_config, load_config
from database import Database
from lead_scorer import score_and_segment_lead
from main import CampaignRunStats, read_leads, import_leads_to_db, run_campaign
from reply_manager import ReplyManager


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.example.json"
UPLOAD_DIR = BASE_DIR / "uploads"

app = Flask(__name__)
app.config["SECRET_KEY"] = "replace-this-in-production"

db = Database()
db.seed_default_canned_responses()
analytics_engine = Analytics(db)
reply_mgr = ReplyManager(db)


class CampaignController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._status: Dict[str, Any] = {
            "running": False,
            "message": "Idle",
            "started_at": "",
            "finished_at": "",
            "current_recipient": "",
            "attempted": 0,
            "sent": 0,
            "failed": 0,
            "skipped_duplicates": 0,
            "total_leads": 0,
            "stopped_by_user": False,
            "last_error": "",
            "campaign_type": "initial",
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self, config_path: Path, campaign_type: str = "initial") -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False

            self._stop_event.clear()
            self._status.update(
                {
                    "running": True,
                    "message": f"{campaign_type.title()} campaign started.",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": "",
                    "current_recipient": "",
                    "attempted": 0,
                    "sent": 0,
                    "failed": 0,
                    "skipped_duplicates": 0,
                    "total_leads": 0,
                    "stopped_by_user": False,
                    "last_error": "",
                    "campaign_type": campaign_type,
                }
            )

            self._thread = threading.Thread(
                target=self._run,
                args=(config_path, campaign_type),
                daemon=True,
                name="campaign-runner",
            )
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                return False
            self._stop_event.set()
            self._status["message"] = "Stop requested. Waiting for safe exit..."
            return True

    def _run(self, config_path: Path, campaign_type: str) -> None:
        try:
            config = load_config(str(config_path))
            config.validate()
            final_stats = run_campaign(
                config=config,
                stop_requested=self._stop_event.is_set,
                progress_callback=self._on_progress,
                campaign_type=campaign_type,
            )
            self._set_finished(final_stats)
        except Exception as exc:
            with self._lock:
                self._status.update(
                    {
                        "running": False,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "message": "Campaign failed.",
                        "last_error": str(exc),
                    }
                )

    def _on_progress(self, stats: CampaignRunStats) -> None:
        with self._lock:
            self._status.update(
                {
                    "running": True,
                    "message": stats.summary or "Campaign in progress...",
                    "started_at": stats.started_at,
                    "finished_at": stats.finished_at,
                    "current_recipient": stats.current_recipient,
                    "attempted": stats.attempted,
                    "sent": stats.sent,
                    "failed": stats.failed,
                    "skipped_duplicates": stats.skipped_duplicates,
                    "total_leads": stats.total_leads,
                    "stopped_by_user": stats.stopped_by_user,
                }
            )

    def _set_finished(self, stats: CampaignRunStats) -> None:
        with self._lock:
            self._status.update(
                {
                    "running": False,
                    "message": stats.summary or "Campaign finished.",
                    "started_at": stats.started_at,
                    "finished_at": stats.finished_at,
                    "current_recipient": stats.current_recipient,
                    "attempted": stats.attempted,
                    "sent": stats.sent,
                    "failed": stats.failed,
                    "skipped_duplicates": stats.skipped_duplicates,
                    "total_leads": stats.total_leads,
                    "stopped_by_user": stats.stopped_by_user,
                }
            )


controller = CampaignController()


def ensure_runtime_files() -> None:
    export_default_config()
    if not CONFIG_PATH.exists() and CONFIG_EXAMPLE_PATH.exists():
        shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_config_json() -> Dict[str, Any]:
    ensure_runtime_files()
    if not CONFIG_PATH.exists():
        return {}

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("config.json must be a JSON object")
    return data


def save_config_json(payload: Dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def read_recent_logs(limit: int = 50) -> List[Dict[str, str]]:
    config = load_config(str(CONFIG_PATH))
    log_path = BASE_DIR / config.logs_csv_path
    if not log_path.exists():
        return []

    rows: deque[Dict[str, str]] = deque(maxlen=limit)
    with log_path.open("r", encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            rows.append({
                "timestamp": str(row.get("timestamp", "")),
                "recipient_email": str(row.get("recipient_email", "")),
                "sender_email": str(row.get("sender_email", "")),
                "status": str(row.get("status", "")),
                "error": str(row.get("error", "")),
            })
    return list(rows)[::-1]


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ─── Page Route ───────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def dashboard() -> str:
    config_data = load_config_json()
    body_templates = config_data.get("body_templates", list(DEFAULT_BODY_TEMPLATES))
    if not isinstance(body_templates, list):
        body_templates = list(DEFAULT_BODY_TEMPLATES)

    while len(body_templates) < 7:
        body_templates.append(DEFAULT_BODY_TEMPLATES[len(body_templates) % len(DEFAULT_BODY_TEMPLATES)])
    body_templates = body_templates[:7]

    status_data = controller.status()
    recent_logs = read_recent_logs(limit=25)
    kpis = analytics_engine.get_kpis()
    funnel = analytics_engine.get_funnel_data()
    pending_replies = reply_mgr.get_pending_replies()
    all_leads = db.get_all_leads()
    canned = reply_mgr.get_canned_responses()

    return render_template(
        "index.html",
        config=config_data,
        status=status_data,
        logs=recent_logs,
        body_templates=body_templates,
        kpis=kpis,
        funnel=funnel,
        pending_replies=pending_replies,
        all_leads=all_leads,
        canned_responses=canned,
    )


# ─── Settings ─────────────────────────────────────────────────────────

@app.route("/save-settings", methods=["POST"])
def save_settings() -> Any:
    config_data = load_config_json()

    config_data["leads_csv_path"] = request.form.get("leads_csv_path", "leads.csv").strip() or "leads.csv"
    config_data["total_daily_limit"] = _as_int(request.form.get("total_daily_limit"), 250)
    config_data["delay_min_seconds"] = _as_int(request.form.get("delay_min_seconds"), 20)
    config_data["delay_max_seconds"] = _as_int(request.form.get("delay_max_seconds"), 120)
    config_data["dry_run"] = _as_bool(request.form.get("dry_run"))
    config_data["follow_up_enabled"] = _as_bool(request.form.get("follow_up_enabled"))
    config_data["follow_up_day_1"] = _as_int(request.form.get("follow_up_day_1"), 3)
    config_data["follow_up_day_2"] = _as_int(request.form.get("follow_up_day_2"), 6)
    config_data["demo_base_url"] = request.form.get("demo_base_url", "").strip()
    config_data["physical_address"] = request.form.get("physical_address", "Islamabad, Pakistan").strip()

    priority_text = request.form.get("sender_type_priority", "zoho,brevo,gmail,outlook")
    config_data["sender_type_priority"] = [
        token.strip().lower()
        for token in priority_text.split(",")
        if token.strip()
    ]

    current_templates = config_data.get("body_templates", list(DEFAULT_BODY_TEMPLATES))
    if not isinstance(current_templates, list):
        current_templates = list(DEFAULT_BODY_TEMPLATES)

    updated_body_templates: List[str] = []
    for index in range(7):
        submitted = request.form.get(f"body_template_{index}", "")
        candidate = submitted.strip()
        if not candidate:
            if index < len(current_templates) and str(current_templates[index]).strip():
                candidate = str(current_templates[index]).strip()
            elif index < len(DEFAULT_BODY_TEMPLATES):
                candidate = DEFAULT_BODY_TEMPLATES[index]
            else:
                candidate = DEFAULT_BODY_TEMPLATES[0]
        updated_body_templates.append(candidate)

    config_data["body_templates"] = updated_body_templates

    senders = config_data.get("senders", [])
    updated_senders = []
    for index, sender in enumerate(senders):
        item = dict(sender)
        item["enabled"] = _as_bool(request.form.get(f"sender_{index}_enabled"))
        item["daily_limit"] = _as_int(request.form.get(f"sender_{index}_daily_limit"), _as_int(sender.get("daily_limit"), 1))
        item["username"] = request.form.get(f"sender_{index}_username", str(sender.get("username", ""))).strip()
        item["password_env"] = request.form.get(f"sender_{index}_password_env", str(sender.get("password_env", ""))).strip()
        item["from_name"] = request.form.get(f"sender_{index}_from_name", str(sender.get("from_name", ""))).strip()
        updated_senders.append(item)

    config_data["senders"] = updated_senders

    save_config_json(config_data)
    return redirect(url_for("dashboard", saved="1"))


# ─── Lead Upload ──────────────────────────────────────────────────────

@app.route("/upload-leads", methods=["POST"])
def upload_leads() -> Any:
    upload = request.files.get("leads_file")
    if not upload or not upload.filename:
        return redirect(url_for("dashboard", upload="0"))

    safe_name = secure_filename(upload.filename)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_path = UPLOAD_DIR / f"{timestamp}_{safe_name}"
    upload.save(target_path)

    config_data = load_config_json()
    config_data["leads_csv_path"] = str(target_path.relative_to(BASE_DIR)).replace("\\", "/")
    save_config_json(config_data)

    # Also import into database
    try:
        leads = read_leads(str(target_path))
        imported = import_leads_to_db(leads, db)
    except Exception:
        imported = 0

    return redirect(url_for("dashboard", upload="1", imported=imported))


# ─── Campaign Control ────────────────────────────────────────────────

@app.route("/start", methods=["POST"])
def start_campaign() -> Any:
    campaign_type = request.form.get("campaign_type", "initial")
    started = controller.start(CONFIG_PATH, campaign_type)
    if not started:
        return redirect(url_for("dashboard", started="0"))
    return redirect(url_for("dashboard", started="1"))


@app.route("/stop", methods=["POST"])
def stop_campaign() -> Any:
    stopped = controller.stop()
    return redirect(url_for("dashboard", stopped="1" if stopped else "0"))


# ─── Status & Logs API ───────────────────────────────────────────────

@app.route("/status", methods=["GET"])
def campaign_status() -> Any:
    return jsonify(controller.status())


@app.route("/logs/recent", methods=["GET"])
def recent_logs() -> Any:
    limit = _as_int(request.args.get("limit"), 50)
    return jsonify({"rows": read_recent_logs(limit=max(1, min(limit, 200)))})


# ─── Leads API ────────────────────────────────────────────────────────

@app.route("/api/leads", methods=["GET"])
def api_leads() -> Any:
    segment = request.args.get("segment")
    funnel = request.args.get("funnel_stage")
    leads = db.get_all_leads(segment=segment, funnel_stage=funnel)
    return jsonify({"leads": leads, "total": len(leads)})


@app.route("/api/leads/<int:lead_id>", methods=["GET"])
def api_lead_detail(lead_id: int) -> Any:
    lead = db.get_lead_by_id(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    sends = db.get_sends_for_lead(lead_id)
    events = db.get_funnel_events(lead_id)
    return jsonify({"lead": lead, "sends": sends, "events": events})


@app.route("/api/leads/<int:lead_id>/funnel", methods=["POST"])
def api_add_funnel_event(lead_id: int) -> Any:
    data = request.get_json(force=True)
    event_type = data.get("event_type", "")
    notes = data.get("notes", "")
    lost_reason = data.get("lost_reason", "")

    if not event_type:
        return jsonify({"error": "event_type required"}), 400

    db.add_funnel_event(lead_id, event_type, notes, lost_reason)
    return jsonify({"ok": True})


# ─── Replies API ──────────────────────────────────────────────────────

@app.route("/api/replies", methods=["GET"])
def api_replies() -> Any:
    handled_param = request.args.get("handled")
    if handled_param == "true":
        replies = reply_mgr.get_all_replies()
        replies = [r for r in replies if r["handled"]]
    elif handled_param == "false":
        replies = reply_mgr.get_pending_replies()
    else:
        replies = reply_mgr.get_all_replies()
    return jsonify({"replies": replies})


@app.route("/api/replies", methods=["POST"])
def api_add_reply() -> Any:
    data = request.get_json(force=True)
    lead_id = data.get("lead_id")
    if not lead_id:
        # Try by email
        email = data.get("email", "")
        lead = db.get_lead_by_email(email)
        if lead:
            lead_id = lead["id"]
        else:
            return jsonify({"error": "lead_id or valid email required"}), 400

    reply_id = reply_mgr.log_reply(
        lead_id=lead_id,
        reply_text=data.get("reply_text", ""),
        reply_type=data.get("reply_type", "unclassified"),
    )
    return jsonify({"ok": True, "reply_id": reply_id})


@app.route("/api/replies/<int:reply_id>/classify", methods=["POST"])
def api_classify_reply(reply_id: int) -> Any:
    data = request.get_json(force=True)
    reply_type = data.get("reply_type", "")
    notes = data.get("notes", "")
    if not reply_type:
        return jsonify({"error": "reply_type required"}), 400
    try:
        reply_mgr.classify_reply(reply_id, reply_type, notes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


# ─── Analytics API ────────────────────────────────────────────────────

@app.route("/api/analytics/kpis", methods=["GET"])
def api_kpis() -> Any:
    return jsonify(analytics_engine.get_kpis())


@app.route("/api/analytics/funnel", methods=["GET"])
def api_funnel() -> Any:
    return jsonify(analytics_engine.get_funnel_data())


@app.route("/api/analytics/templates", methods=["GET"])
def api_template_performance() -> Any:
    return jsonify({"templates": analytics_engine.get_template_performance()})


@app.route("/api/analytics/daily", methods=["GET"])
def api_daily_stats() -> Any:
    days = _as_int(request.args.get("days"), 30)
    return jsonify({"daily": analytics_engine.get_daily_stats(days)})


# ─── Suppression API ─────────────────────────────────────────────────

@app.route("/api/suppression", methods=["GET"])
def api_suppression() -> Any:
    return jsonify({"list": db.get_suppression_list()})


@app.route("/api/suppression", methods=["POST"])
def api_add_suppression() -> Any:
    data = request.get_json(force=True)
    email = data.get("email", "").strip()
    reason = data.get("reason", "manual")
    if not email:
        return jsonify({"error": "email required"}), 400
    db.add_to_suppression(email, reason)
    return jsonify({"ok": True})


# ─── Canned Responses API ────────────────────────────────────────────

@app.route("/api/canned-responses", methods=["GET"])
def api_canned_responses() -> Any:
    return jsonify({"responses": db.get_canned_responses()})


@app.route("/api/canned-responses", methods=["POST"])
def api_add_canned_response() -> Any:
    data = request.get_json(force=True)
    trigger = data.get("trigger_type", "")
    title = data.get("title", "")
    text = data.get("response_text", "")
    if not trigger or not text:
        return jsonify({"error": "trigger_type and response_text required"}), 400
    rid = db.add_canned_response(trigger, title, text)
    return jsonify({"ok": True, "id": rid})


# ─── Campaigns API ───────────────────────────────────────────────────

@app.route("/api/campaigns", methods=["GET"])
def api_campaigns() -> Any:
    return jsonify({"campaigns": db.get_campaigns()})


if __name__ == "__main__":
    ensure_runtime_files()
    app.run(host="127.0.0.1", port=5000, debug=False)
