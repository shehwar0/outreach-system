from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_SENDER_SPECS = [
    {"email": "info@asagus.com", "type": "zoho", "limit": 95},
    {"email": "hello@asagus.com", "type": "zoho", "limit": 95},
    {"email": "contact@asagus.com", "type": "brevo", "limit": 100},
    {"email": "abc@gmail.com", "type": "gmail", "limit": 30},
    {"email": "xyz@gmail.com", "type": "gmail", "limit": 30},
    {"email": "abc@outlook.com", "type": "outlook", "limit": 30},
]


DEFAULT_BODY_TEMPLATES = [
    "Hi {name},\n\n{context_line}\n\nI noticed {business} does not have a website yet. Most customers {city} search online before choosing a service, and a simple homepage could help you get more calls.\n\nWould it be worth a quick look at how that could work for you?\n\nBest regards,",
    "Hello {name},\n\n{context_line}\n\nI work with small businesses {city} on getting their first website up. A basic homepage for {business} could help new customers find and trust you more easily.\n\nHappy to share a quick example if you are curious.\n\nBest,",
    "Hi {name},\n\n{context_line}\n\nI noticed {business} {city} does not seem to have a website yet. In my experience, even a simple one-page site can bring in a few extra calls each week.\n\nWould you be open to seeing how that might look for your business?\n\nRegards,",
    "Hello {name},\n\n{context_line}\n\nQuick question — have you thought about having a website for {business} {city}? A lot of your competitors already have one, and customers tend to pick businesses they can look up online.\n\nI can show you a short example if you are interested.\n\nThanks,",
    "Hi {name},\n\n{context_line}\n\nI put together a quick demo homepage for {business} to show what a website could look like for you: {demo_link}\n\nIt is just an example, but it gives you an idea of how customers {city} would find you online.\n\nWorth a look?\n\nBest regards,",
    "Hello {name},\n\n{context_line}\n\nYour reviews for {business} {city} are impressive. A website would make it even easier for new customers to find you and get in touch directly.\n\nI can share a quick example if you want to see how it would look.\n\nRegards,",
    "Hi {name},\n\n{context_line}\n\nI came across {business} {city} and noticed you do not have a website yet. I help local businesses get a simple, professional homepage that brings in more calls and bookings.\n\nInterested in seeing a quick example?\n\nThank you,",
]


@dataclass
class SenderConfig:
    email: str
    type: str
    daily_limit: int
    enabled: bool = True
    username: Optional[str] = None
    password: Optional[str] = None
    password_env: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    use_tls: bool = True
    brevo_api_key: Optional[str] = None
    brevo_api_key_env: Optional[str] = None
    from_name: Optional[str] = None
    sent_count: int = 0

    def resolved_password(self) -> Optional[str]:
        if self.password:
            return self.password
        if self.password_env:
            return os.getenv(self.password_env)
        return None

    def resolved_brevo_api_key(self) -> Optional[str]:
        if self.brevo_api_key:
            return self.brevo_api_key
        if self.brevo_api_key_env:
            return os.getenv(self.brevo_api_key_env)
        return None


@dataclass
class AIConfig:
    enabled: bool = False
    provider: str = "disabled"
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 20
    temperature: float = 0.7

    def resolved_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        return os.getenv(self.api_key_env)


@dataclass
class AppConfig:
    leads_csv_path: str = "leads.csv"
    logs_csv_path: str = "logs/activity_log.csv"
    logs_jsonl_path: str = "logs/activity_log.jsonl"
    sent_recipients_path: str = "logs/sent_recipients.json"
    dry_run: bool = True
    total_daily_limit: int = 250
    delay_min_seconds: int = 20
    delay_max_seconds: int = 120
    sender_type_priority: List[str] = field(default_factory=lambda: ["zoho", "brevo", "gmail", "outlook"])
    senders: List[SenderConfig] = field(default_factory=list)
    subject_templates: List[str] = field(
        default_factory=lambda: [
            "Quick idea for {business}",
            "Getting more bookings for {business}",
            "A short question, {name}",
            "Thought about {business} {city}",
            "Saw your reviews, {name}",
            "Quick thought for {business}",
            "One idea for {business} {city}",
        ]
    )
    body_templates: List[str] = field(default_factory=lambda: list(DEFAULT_BODY_TEMPLATES))
    ai: AIConfig = field(default_factory=AIConfig)
    follow_up_enabled: bool = True
    follow_up_day_1: int = 3
    follow_up_day_2: int = 6
    demo_base_url: str = ""
    physical_address: str = "Islamabad, Pakistan"
    unsubscribe_text: str = "Reply STOP to unsubscribe | {physical_address}"

    def validate(self) -> None:
        if self.delay_min_seconds < 0 or self.delay_max_seconds < 0:
            raise ValueError("Delay values must be >= 0.")
        if self.delay_min_seconds > self.delay_max_seconds:
            raise ValueError("delay_min_seconds cannot be greater than delay_max_seconds.")
        if self.total_daily_limit <= 0:
            raise ValueError("total_daily_limit must be > 0.")

        for sender in self.senders:
            if sender.daily_limit <= 0:
                raise ValueError(f"Sender {sender.email} has non-positive daily_limit.")
            if sender.type.lower() not in {"zoho", "brevo", "gmail", "outlook"}:
                raise ValueError(f"Sender {sender.email} has unsupported type: {sender.type}")

        if len(self.body_templates) < 1:
            raise ValueError("body_templates must contain at least 1 template.")

        for index, template in enumerate(self.body_templates):
            normalized = str(template).strip()
            if not normalized:
                raise ValueError(f"body_templates[{index}] cannot be empty.")


def _default_sender_configs() -> List[SenderConfig]:
    return [
        SenderConfig(
            email=item["email"],
            type=item["type"],
            daily_limit=int(item["limit"]),
        )
        for item in DEFAULT_SENDER_SPECS
    ]


def _build_sender(raw: Dict[str, Any]) -> SenderConfig:
    daily_limit = raw.get("daily_limit", raw.get("limit", 0))
    return SenderConfig(
        email=str(raw.get("email", "")).strip(),
        type=str(raw.get("type", "")).strip().lower(),
        daily_limit=int(daily_limit),
        enabled=bool(raw.get("enabled", True)),
        username=raw.get("username"),
        password=raw.get("password"),
        password_env=raw.get("password_env"),
        smtp_host=raw.get("smtp_host"),
        smtp_port=int(raw["smtp_port"]) if raw.get("smtp_port") else None,
        use_tls=bool(raw.get("use_tls", True)),
        brevo_api_key=raw.get("brevo_api_key"),
        brevo_api_key_env=raw.get("brevo_api_key_env"),
        from_name=raw.get("from_name"),
        sent_count=int(raw.get("sent_count", 0)),
    )


def _build_ai_config(raw: Dict[str, Any]) -> AIConfig:
    return AIConfig(
        enabled=bool(raw.get("enabled", False)),
        provider=str(raw.get("provider", "disabled")),
        endpoint=str(raw.get("endpoint", "https://api.openai.com/v1/chat/completions")),
        model=str(raw.get("model", "gpt-4o-mini")),
        api_key=raw.get("api_key"),
        api_key_env=str(raw.get("api_key_env", "OPENAI_API_KEY")),
        timeout_seconds=int(raw.get("timeout_seconds", 20)),
        temperature=float(raw.get("temperature", 0.7)),
    )


def app_config_from_dict(raw: Dict[str, Any]) -> AppConfig:
    senders_raw = raw.get("senders") or []
    senders = [_build_sender(item) for item in senders_raw] if senders_raw else _default_sender_configs()

    ai_config = _build_ai_config(raw.get("ai", {}))

    config = AppConfig(
        leads_csv_path=str(raw.get("leads_csv_path", "leads.csv")),
        logs_csv_path=str(raw.get("logs_csv_path", "logs/activity_log.csv")),
        logs_jsonl_path=str(raw.get("logs_jsonl_path", "logs/activity_log.jsonl")),
        sent_recipients_path=str(raw.get("sent_recipients_path", "logs/sent_recipients.json")),
        dry_run=bool(raw.get("dry_run", True)),
        total_daily_limit=int(raw.get("total_daily_limit", 250)),
        delay_min_seconds=int(raw.get("delay_min_seconds", 20)),
        delay_max_seconds=int(raw.get("delay_max_seconds", 120)),
        sender_type_priority=[str(item).lower() for item in raw.get("sender_type_priority", ["zoho", "brevo", "gmail", "outlook"])],
        senders=senders,
        subject_templates=[str(item) for item in raw.get("subject_templates", AppConfig().subject_templates)],
        body_templates=[str(item) for item in raw.get("body_templates", list(DEFAULT_BODY_TEMPLATES))],
        ai=ai_config,
        follow_up_enabled=bool(raw.get("follow_up_enabled", True)),
        follow_up_day_1=int(raw.get("follow_up_day_1", 3)),
        follow_up_day_2=int(raw.get("follow_up_day_2", 6)),
        demo_base_url=str(raw.get("demo_base_url", "")),
        physical_address=str(raw.get("physical_address", "Islamabad, Pakistan")),
        unsubscribe_text=str(raw.get("unsubscribe_text", "Reply STOP to unsubscribe | {physical_address}")),
    )
    config.validate()
    return config


def load_config(config_path: str = "config.json") -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        config = AppConfig(senders=_default_sender_configs())
        config.validate()
        return config

    with path.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a JSON object.")

    return app_config_from_dict(raw)


def export_default_config(config_path: str = "config.example.json") -> None:
    path = Path(config_path)
    if path.exists():
        return

    default_config = AppConfig(senders=_default_sender_configs())
    payload: Dict[str, Any] = {
        "leads_csv_path": default_config.leads_csv_path,
        "logs_csv_path": default_config.logs_csv_path,
        "logs_jsonl_path": default_config.logs_jsonl_path,
        "sent_recipients_path": default_config.sent_recipients_path,
        "dry_run": default_config.dry_run,
        "total_daily_limit": default_config.total_daily_limit,
        "delay_min_seconds": default_config.delay_min_seconds,
        "delay_max_seconds": default_config.delay_max_seconds,
        "sender_type_priority": default_config.sender_type_priority,
        "senders": [
            {
                "email": sender.email,
                "type": sender.type,
                "daily_limit": sender.daily_limit,
                "enabled": sender.enabled,
                "username": sender.username,
                "password": sender.password,
                "password_env": sender.password_env,
                "smtp_host": sender.smtp_host,
                "smtp_port": sender.smtp_port,
                "use_tls": sender.use_tls,
                "brevo_api_key": sender.brevo_api_key,
                "brevo_api_key_env": sender.brevo_api_key_env,
                "from_name": sender.from_name,
            }
            for sender in default_config.senders
        ],
        "subject_templates": default_config.subject_templates,
        "body_templates": default_config.body_templates,
        "ai": {
            "enabled": default_config.ai.enabled,
            "provider": default_config.ai.provider,
            "endpoint": default_config.ai.endpoint,
            "model": default_config.ai.model,
            "api_key": default_config.ai.api_key,
            "api_key_env": default_config.ai.api_key_env,
            "timeout_seconds": default_config.ai.timeout_seconds,
            "temperature": default_config.ai.temperature,
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
