from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Dict, Tuple
from urllib import error as url_error
from urllib import request as url_request

from config import SenderConfig


SMTP_DEFAULTS: Dict[str, Tuple[str, int, bool]] = {
    "zoho": ("smtp.zoho.com", 587, True),
    "gmail": ("smtp.gmail.com", 587, True),
    "outlook": ("smtp-mail.outlook.com", 587, True),
    "brevo": ("smtp-relay.brevo.com", 587, True),
}


class EmailDeliveryError(Exception):
    pass


class EmailSender:
    def __init__(self, dry_run: bool = True, timeout_seconds: int = 30) -> None:
        self._dry_run = dry_run
        self._timeout_seconds = timeout_seconds

    def send_email(self, sender: SenderConfig, recipient_email: str, subject: str, body: str) -> None:
        if self._dry_run:
            return

        sender_type = sender.type.lower().strip()
        if sender_type == "brevo" and sender.resolved_brevo_api_key():
            self._send_via_brevo_api(sender=sender, recipient_email=recipient_email, subject=subject, body=body)
            return

        self._send_via_smtp(sender=sender, recipient_email=recipient_email, subject=subject, body=body)

    def _send_via_smtp(self, sender: SenderConfig, recipient_email: str, subject: str, body: str) -> None:
        sender_type = sender.type.lower().strip()
        default_host, default_port, default_tls = SMTP_DEFAULTS.get(sender_type, (None, None, True))

        smtp_host = sender.smtp_host or default_host
        smtp_port = sender.smtp_port or default_port
        use_tls = sender.use_tls if sender.use_tls is not None else default_tls

        if not smtp_host or not smtp_port:
            raise EmailDeliveryError(f"SMTP profile is missing for sender type: {sender_type}")

        username = sender.username or ("apikey" if sender_type == "brevo" else sender.email)
        password = sender.resolved_password()
        if not password:
            raise EmailDeliveryError(f"Missing SMTP credential for sender {sender.email}")

        msg = EmailMessage()
        display_name = sender.from_name or sender.email
        msg["From"] = formataddr((display_name, sender.email))
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=self._timeout_seconds) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(str(exc)) from exc

    def _send_via_brevo_api(self, sender: SenderConfig, recipient_email: str, subject: str, body: str) -> None:
        api_key = sender.resolved_brevo_api_key()
        if not api_key:
            raise EmailDeliveryError("Brevo API key not available.")

        payload = {
            "sender": {
                "name": sender.from_name or sender.email,
                "email": sender.email,
            },
            "to": [{"email": recipient_email}],
            "subject": subject,
            "textContent": body,
        }

        data = json.dumps(payload).encode("utf-8")
        req = url_request.Request(
            "https://api.brevo.com/v3/smtp/email",
            method="POST",
            data=data,
            headers={
                "Content-Type": "application/json",
                "api-key": api_key,
                "accept": "application/json",
            },
        )

        try:
            with url_request.urlopen(req, timeout=self._timeout_seconds) as response:
                code = response.getcode()
                if code < 200 or code >= 300:
                    raise EmailDeliveryError(f"Brevo API returned status code {code}")
        except (url_error.URLError, TimeoutError, OSError) as exc:
            raise EmailDeliveryError(str(exc)) from exc
