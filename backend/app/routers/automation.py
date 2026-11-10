"""Landlord automation log and authenticated WhatsApp webhooks."""
from datetime import timezone
import hashlib
import hmac
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import require_landlord
from ..security import is_fixture_account
from ..services.automation import handle_inbound
from ..services.automation_channels import (
    DELIVERY_RANK, canonical_phone, parse_delivery_status,
)

router = APIRouter(prefix="/automation", tags=["automation"])


def scoped_tenants(agency_id):
    return select(m.User).join(m.Lease, m.Lease.tenant_id == m.User.id).join(
        m.Unit, m.Unit.id == m.Lease.unit_id).join(m.Property, m.Property.id == m.Unit.property_id
    ).where(m.Property.landlord_id == agency_id, m.User.role == "tenant").distinct()


def message_out(row, name):
    values = {key: getattr(row, key) for key in (
        "id", "tenant_id", "kind", "channel", "direction", "status", "mode", "subject",
        "body", "error", "request_id", "provider_message_id", "answered_at")}
    values.update(billable=row.billable, cost_estimate=row.cost_estimate,
                  actual_cost=row.actual_cost, cost_currency=row.cost_currency,
                  actual_cost_currency=row.actual_cost_currency)
    for key in ("created_at", "sent_at", "delivered_at", "read_at"):
        timestamp = getattr(row, key)
        values[key] = timestamp.replace(tzinfo=timezone.utc) if timestamp else None
    return {**values, "tenant": name}


@router.get("/log")
def log(tenant_id: int | None = None, kind: str | None = None, channel: str | None = None,
        status: str | None = None, limit: int = Query(default=100, ge=1, le=500),
        agency=Depends(require_landlord), db: Session = Depends(get_db)):
    query = select(m.AutomationMessage, m.User.full_name).join(
        m.User, m.User.id == m.AutomationMessage.tenant_id).where(m.AutomationMessage.agency_id == agency.id)
    for column, value in ((m.AutomationMessage.tenant_id, tenant_id), (m.AutomationMessage.kind, kind),
                          (m.AutomationMessage.channel, channel), (m.AutomationMessage.status, status)):
        if value is not None:
            query = query.where(column == value)
    rows = db.execute(query.order_by(m.AutomationMessage.id.desc()).limit(limit))
    return {"messages": [message_out(row, name) for row, name in rows],
            "tenants": [{"id": tenant.id, "name": tenant.full_name} for tenant in
                        db.scalars(scoped_tenants(agency.id).order_by(m.User.full_name))]}


@router.get("/whatsapp/webhook")
def verify_webhook(request: Request):
    query = request.query_params
    token = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
    if token and query.get("hub.mode") == "subscribe" and hmac.compare_digest(
        token.encode(), query.get("hub.verify_token", "").encode()
    ):
        return PlainTextResponse(query.get("hub.challenge", ""))
    raise HTTPException(403, "Webhook verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(expected.encode(),
            request.headers.get("X-Hub-Signature-256", "").encode()):
        raise HTTPException(403, "Invalid webhook signature")
    try:
        payload = await request.json()
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "messages":
                    apply_whatsapp_event(db, change["value"])
    except (ValueError, AttributeError, KeyError, TypeError):
        db.rollback()
        raise HTTPException(400, "Invalid webhook payload") from None
    db.commit()
    return {"ok": True}


def apply_whatsapp_event(db, event):
    phone_id = event.get("metadata", {}).get("phone_number_id")
    if not phone_id or phone_id != os.getenv("WHATSAPP_PHONE_NUMBER_ID"):
        return
    mode = "real"
    for item in event.get("statuses", []):
        status = parse_delivery_status(item.get("status"))
        if not status or not item.get("id"):
            continue
        lower_statuses = [name for name, rank in DELIVERY_RANK.items() if rank < DELIVERY_RANK[status]]
        values = {"status": status}
        if status in {"delivered", "read"}:
            values["delivered_at" if status == "delivered" else "read_at"] = m.utcnow()
        if status == "failed":
            values["error"] = "Meta reported delivery failure"
        elif status in {"delivered", "read"}:
            values["error"] = None
        db.execute(update(m.AutomationMessage).where(m.AutomationMessage.provider_message_id == item["id"],
            m.AutomationMessage.direction == "outbound", m.AutomationMessage.mode == mode,
            m.AutomationMessage.status.in_(lower_statuses)).values(**values))
    for item in event.get("messages", []):
        number = canonical_phone(item.get("from", ""))
        text = item.get("text", {}).get("body", "").strip()
        if not number or not text or not item.get("id"):
            continue
        candidates = db.execute(select(m.AutomationMessage.agency_id, m.User).join(
            m.User, m.User.id == m.AutomationMessage.tenant_id).where(
            m.AutomationMessage.channel == "whatsapp", m.AutomationMessage.mode == mode,
            m.AutomationMessage.direction == "outbound", m.AutomationMessage.status.in_(("sent", "delivered", "read")),
            m.User.phone.in_((number, "+" + number))).distinct()).all()
        reply_to = item.get("context", {}).get("id")
        if reply_to:
            prompt = db.scalar(select(m.AutomationMessage).where(
                m.AutomationMessage.provider_message_id == reply_to,
                m.AutomationMessage.mode == mode, m.AutomationMessage.direction == "outbound"))
            candidates = [(agency, tenant) for agency, tenant in candidates if prompt
                          and (agency, tenant.id) == (prompt.agency_id, prompt.tenant_id)]
        if len(candidates) == 1 and not is_fixture_account(candidates[0][1].email):
            agency, tenant = candidates[0]
            handle_inbound(db, agency, tenant, text[:1000],
                           message_id=item["id"], reply_to=reply_to)
