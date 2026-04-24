from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Set


@dataclass
class OutreachLogRecord:
    recipient_email: str
    sender_email: str
    sender_type: str
    subject: str
    status: str
    timestamp: str
    error: str = ""


class OutreachLogger:
    CSV_FIELDS = [
        "timestamp",
        "recipient_email",
        "sender_email",
        "sender_type",
        "subject",
        "status",
        "error",
    ]

    def __init__(self, csv_path: str, jsonl_path: str, sent_recipients_path: str) -> None:
        self._csv_path = Path(csv_path)
        self._jsonl_path = Path(jsonl_path)
        self._sent_recipients_path = Path(sent_recipients_path)
        self._file_lock = Lock()

        self.console = self._build_console_logger()
        self._ensure_files()
        self._sent_recipients: Set[str] = self._load_sent_recipients_file()

    def already_sent(self, recipient_email: str) -> bool:
        return recipient_email.strip().lower() in self._sent_recipients

    def mark_sent(self, recipient_email: str) -> None:
        normalized = recipient_email.strip().lower()
        if not normalized:
            return

        self._sent_recipients.add(normalized)
        self._persist_sent_recipients()

    def log_event(self, record: OutreachLogRecord) -> None:
        row = asdict(record)

        with self._file_lock:
            with self._csv_path.open("a", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=self.CSV_FIELDS)
                writer.writerow(row)

            with self._jsonl_path.open("a", encoding="utf-8") as jsonl_file:
                jsonl_file.write(json.dumps(row, ensure_ascii=True) + "\n")

        if record.status == "sent":
            self.console.info("Sent to %s via %s", record.recipient_email, record.sender_email)
        else:
            self.console.warning(
                "Failed for %s via %s: %s",
                record.recipient_email,
                record.sender_email,
                record.error,
            )

    def load_sent_recipients_from_history(self) -> Set[str]:
        sent: Set[str] = set(self._sent_recipients)

        if self._csv_path.exists():
            with self._csv_path.open("r", encoding="utf-8", newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    status = str(row.get("status", "")).strip().lower()
                    if status != "sent":
                        continue

                    email = str(row.get("recipient_email", "")).strip().lower()
                    if email:
                        sent.add(email)

        self._sent_recipients = sent
        self._persist_sent_recipients()
        return sent

    def load_sender_attempt_counts_for_date(self, target_date: date) -> Dict[str, int]:
        counts: Dict[str, int] = {}

        if not self._csv_path.exists():
            return counts

        with self._csv_path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                status = str(row.get("status", "")).strip().lower()
                if status not in {"sent", "failed"}:
                    continue

                timestamp = str(row.get("timestamp", "")).strip()
                parsed_date = self._parse_date(timestamp)
                if parsed_date != target_date:
                    continue

                sender = str(row.get("sender_email", "")).strip().lower()
                if not sender:
                    continue

                counts[sender] = counts.get(sender, 0) + 1

        return counts

    def count_sent_for_date(self, target_date: date) -> int:
        total = 0

        if not self._csv_path.exists():
            return total

        with self._csv_path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                status = str(row.get("status", "")).strip().lower()
                if status != "sent":
                    continue

                timestamp = str(row.get("timestamp", "")).strip()
                parsed_date = self._parse_date(timestamp)
                if parsed_date == target_date:
                    total += 1

        return total

    @staticmethod
    def _parse_date(timestamp: str) -> date | None:
        if not timestamp:
            return None

        try:
            normalized = timestamp.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            return None

    def _ensure_files(self) -> None:
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._sent_recipients_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._csv_path.exists():
            with self._csv_path.open("w", encoding="utf-8", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=self.CSV_FIELDS)
                writer.writeheader()

        if not self._jsonl_path.exists():
            self._jsonl_path.touch()

        if not self._sent_recipients_path.exists():
            with self._sent_recipients_path.open("w", encoding="utf-8") as file:
                json.dump([], file)

    def _load_sent_recipients_file(self) -> Set[str]:
        if not self._sent_recipients_path.exists():
            return set()

        try:
            with self._sent_recipients_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return set()

        if not isinstance(data, list):
            return set()

        return {str(item).strip().lower() for item in data if str(item).strip()}

    def _persist_sent_recipients(self) -> None:
        with self._file_lock:
            with self._sent_recipients_path.open("w", encoding="utf-8") as file:
                json.dump(sorted(self._sent_recipients), file, indent=2)

    @staticmethod
    def _build_console_logger() -> logging.Logger:
        logger = logging.getLogger("cold_outreach")
        if logger.handlers:
            return logger

        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        return logger
