"""Scoped notification delivery and WhatsApp provider configuration."""
import os
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from .. import models as m
from .reminder_senders import ConsoleSender, DeliveryResult, build_sender, send_with_retries

CHANNELS = ("whatsapp", "sms", "email")
DELIVERY_RANK = {"queued": 0, "sent": 1, "failed": 2, "delivered": 3, "read": 4}


def channel_mode(channel: str) -> str:
    mode = os.getenv(f"{channel.upper()}_MODE", "").strip().lower()
    if mode in {"real", "log"}:
        return mode
    return "legacy" if not mode else "log"


def canonical_phone(value: str) -> str:
    number = value.strip().removeprefix("+")
    return number if re.fullmatch(r"[1-9][0-9]{7,14}", number) else ""


def parse_delivery_status(value: str) -> str | None:
    return value if value in {"sent", "delivered", "read", "failed"} else None


class NotificationChannel(Protocol):
    channel: str

    def send(self, recipient: str, subject: str, message: str, *,
             template_variables: dict[str, str] | None = None) -> DeliveryResult: ...

    def parse_delivery_status(self, value: str) -> str | None: ...


@dataclass
class MetaWhatsAppChannel:
    template: str
    channel = "whatsapp"
    parse_delivery_status = staticmethod(parse_delivery_status)

    def send(self, recipient, subject, message, *, template_variables=None):
        phone = canonical_phone(recipient)
        if not phone:
            raise ValueError("WhatsApp requires a valid international phone number")
        phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        token = os.environ.get("WHATSAPP_TOKEN", "")
        version = os.environ.get("WHATSAPP_GRAPH_VERSION", "")
        if not (phone_id.isdecimal() and token and re.fullmatch(r"v[0-9]+\.[0-9]+", version)):
            raise ValueError("WhatsApp credentials or Graph API version are missing")
        name = self.template
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError("An approved WhatsApp template must be configured")
        template = {"name": name, "language": {"code": "en_US"}}
        variables = template_variables or {"1": message}
        template["components"] = [{"type": "body", "parameters": [
            {"type": "text", "text": " ".join(value.split())[:500]}
            for value in variables.values()
        ]}]
        try:
            response = httpx.post(f"https://graph.facebook.com/{version}/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={"messaging_product": "whatsapp", "to": phone, "type": "template",
                      "template": template}, timeout=10)
            response.raise_for_status()
            return DeliveryResult(response.json()["messages"][0]["id"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            raise RuntimeError("Meta rejected the WhatsApp send or its outcome is unknown") from None


def deliver(db, agency_id, tenant, kind, channel, recipient, subject, body, *,
            request_id=None, dedupe_key=None, template_variables=None, sender=None, reservation=None):
    mode = "log" if isinstance(sender, ConsoleSender) else channel_mode(channel)
    row = reservation or m.AutomationMessage(agency_id=agency_id, tenant_id=tenant.id, kind=kind,
        channel=channel, direction="outbound", mode=mode, subject=subject, body=body,
        request_id=request_id, dedupe_key=dedupe_key, status="queued", billable=channel in {"sms", "whatsapp"} and mode != "log")
    db.add(row)
    if dedupe_key:
        db.flush()
    if not recipient:
        row.status = "skipped"
        row.error = "No contact on file"
        return row
    try:
        if sender is None and channel == "whatsapp" and mode == "real":
            adapter = MetaWhatsAppChannel(f"landkeep_{kind}")
            result = adapter.send(recipient, subject, body, template_variables={"1": body})
        else:
            result = send_with_retries(sender or build_sender(channel), recipient, subject, body,
                                       template_variables=template_variables)
        row.sent_at = m.utcnow()
        if row.status == "queued":
            row.status = "sent"
        row.provider_message_id = result.provider_message_id
        row.actual_cost = getattr(result, "actual_cost", None)
        row.actual_cost_currency = getattr(result, "actual_cost_currency", None)
    except (ValueError, RuntimeError) as exc:
        row.status = "failed"
        row.error = str(exc)[:300] if channel == "whatsapp" and mode == "real" else "Provider delivery failed"
    return row
