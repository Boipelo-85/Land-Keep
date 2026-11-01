"""Delivery adapters for rent reminders (all providers are lazy-loaded)."""
from __future__ import annotations

import json
import os
import smtplib
import threading
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol


@dataclass(frozen=True)
class DeliveryResult:
    provider_message_id: str | None = None


class Sender(Protocol):
    channel: str

    def send(self, recipient: str, subject: str, message: str,
             *, template_variables: dict[str, str] | None = None) -> DeliveryResult: ...


class ConsoleSender:
    def __init__(self, channel: str):
        self.channel = channel

    def send(self, recipient: str, subject: str, message: str,
             *, template_variables: dict[str, str] | None = None) -> DeliveryResult:
        print(f"[RENT REMINDER {self.channel.upper()} -> {recipient}] {subject}: {message}")
        return DeliveryResult()


class TwilioSender:
    def __init__(self, channel: str):
        self.channel = channel

    def send(self, recipient: str, subject: str, message: str,
             *, template_variables: dict[str, str] | None = None) -> DeliveryResult:
        from twilio.rest import Client

        account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        client = Client(account_sid, auth_token)
        if self.channel == "sms":
            sent = client.messages.create(
                to=recipient,
                from_=os.environ["TWILIO_SMS_FROM"],
                body=message,
            )
        else:
            content_sid = os.environ["TWILIO_WHATSAPP_CONTENT_SID"]
            sender = os.environ["TWILIO_WHATSAPP_FROM"]
            if not sender.startswith("whatsapp:"):
                sender = f"whatsapp:{sender}"
            sent = client.messages.create(
                to=f"whatsapp:{recipient}",
                from_=sender,
                content_sid=content_sid,
                content_variables=json.dumps(template_variables or {}),
            )
        return DeliveryResult(provider_message_id=sent.sid)


class SmtpEmailSender:
    channel = "email"

    def send(self, recipient: str, subject: str, message: str,
             *, template_variables: dict[str, str] | None = None) -> DeliveryResult:
        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = os.environ["SMTP_FROM"]
        email["To"] = recipient
        email.set_content(message)
        host = os.environ["SMTP_HOST"]
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME")
        password = os.getenv("SMTP_PASSWORD")
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            if username:
                server.login(username, password or "")
            server.send_message(email)
        return DeliveryResult()


_rate_lock = threading.Lock()
_last_send_at = 0.0


def _rate_limit() -> None:
    """Serialize provider sends to avoid bursts against account throughput limits."""
    global _last_send_at
    minimum = float(os.getenv("LANDKEEP_PROVIDER_MIN_INTERVAL_SECONDS", "0.2"))
    with _rate_lock:
        delay = minimum - (time.monotonic() - _last_send_at)
        if delay > 0:
            time.sleep(delay)
        _last_send_at = time.monotonic()


def send_with_retries(sender: Sender, recipient: str, subject: str, message: str,
                      *, template_variables: dict[str, str] | None = None) -> DeliveryResult:
    attempts = max(1, int(os.getenv("LANDKEEP_PROVIDER_MAX_ATTEMPTS", "3")))
    base_delay = max(0.0, float(os.getenv("LANDKEEP_PROVIDER_RETRY_BASE_SECONDS", "1")))
    last_error = None
    for attempt in range(attempts):
        try:
            _rate_limit()
            return sender.send(recipient, subject, message, template_variables=template_variables)
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status", None)
            smtp_code = getattr(exc, "smtp_code", None)
            retryable = (
                status == 429
                or (status is not None and 500 <= status < 600)
                or (smtp_code is not None and 400 <= smtp_code < 500)
                or isinstance(exc, (TimeoutError, ConnectionError, OSError,
                                    smtplib.SMTPServerDisconnected))
            )
            if retryable and attempt + 1 < attempts:
                time.sleep(base_delay * (2 ** attempt))
                continue
            break
    raise RuntimeError(f"{type(last_error).__name__}: {last_error}") from last_error


def build_sender(channel: str) -> Sender:
    if os.getenv("LANDKEEP_REMINDER_CONSOLE", "true").lower() in {"1", "true", "yes"}:
        return ConsoleSender(channel)
    if channel in {"sms", "whatsapp"}:
        return TwilioSender(channel)
    if channel == "email":
        return SmtpEmailSender()
    raise ValueError(f"Unsupported reminder channel: {channel}")
