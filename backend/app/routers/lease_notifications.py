"""Tenant inbox and verified lease notification preferences."""
import hashlib
import hmac
import secrets
from datetime import timedelta
from string import Formatter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import get_current_user, require_landlord, require_tenant
from ..security import SECRET, is_fixture_account
from ..services import lease_notifications as prefs
from ..services.agency_reminders import local_today, normalize_sa_phone, run_reminders
from ..services.reminder_senders import ConsoleSender, build_sender, send_with_retries

router = APIRouter(prefix="/lease-notifications", tags=["lease notifications"])
Channel = Literal["email", "sms", "whatsapp"]


def lease_context(db, lease_id, user):
    row = db.execute(select(m.Lease, m.Property).join(m.Unit, m.Unit.id == m.Lease.unit_id)
        .join(m.Property, m.Property.id == m.Unit.property_id).where(m.Lease.id == lease_id)).first()
    if row is None or (row.Lease.tenant_id != user.id if user.role == "tenant" else row.Property.landlord_id != user.id):
        raise HTTPException(404, "Lease not found")
    return row


def preference_view(db, lease, prop, user):
    allowed = prefs.available_channels(prefs.policy_for(db, prop.landlord_id), prop.id)
    selected = prefs.choices(db, lease)
    return {"channels": [{"channel": channel, "enabled": selected[channel],
                         "verified": prefs.verified(db, user, channel)} for channel in allowed]}


class Selection(BaseModel):
    channels: set[Channel] = Field(min_length=1, max_length=3)


@router.get("/leases/{lease_id}")
def get_preferences(lease_id: int, user=Depends(require_tenant), db: Session = Depends(get_db)):
    lease, prop = lease_context(db, lease_id, user)
    return preference_view(db, lease, prop, user)


@router.put("/leases/{lease_id}")
def save_preferences(lease_id: int, body: Selection, user=Depends(require_tenant), db: Session = Depends(get_db)):
    lease, prop = lease_context(db, lease_id, user)
    if lease.status not in {"pending", "active"}:
        raise HTTPException(409, "This lease has ended")
    allowed = prefs.available_channels(prefs.policy_for(db, prop.landlord_id), prop.id)
    if not body.channels.issubset(allowed):
        raise HTTPException(400, "A selected channel is disabled for this lease")
    for channel in body.channels:
        if not prefs.verified(db, user, channel):
            raise HTTPException(400, f"Verify your {prefs.contact_kind(channel)} before selecting {channel}")
    current = prefs.choices(db, lease)
    for channel in prefs.EXTERNAL_CHANNELS:
        enabled = channel in body.channels
        if current[channel] != enabled or db.get(m.LeaseNotificationPreference, (lease.id, channel)) is None:
            prefs.save_choice(db, lease, prop.landlord_id, channel, enabled, user.id, "tenant")
    db.commit()
    return preference_view(db, lease, prop, user)


class ContactRequest(BaseModel):
    phone: str | None = Field(default=None, max_length=30)


class ContactCode(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


def code_digest(user_id, kind, contact, code):
    return hmac.new(SECRET.encode(), f"{user_id}:{kind}:{contact}:{code}".encode(), hashlib.sha256).hexdigest()


@router.post("/verify/{kind}/request")
def request_code(kind: Literal["email", "phone"], body: ContactRequest,
                 user=Depends(require_tenant), db: Session = Depends(get_db)):
    if is_fixture_account(user.email) and not prefs.demo_mode():
        raise HTTPException(409, "Enable local demo mode to verify a demo contact")
    contact = user.email
    channel = "email"
    if kind == "phone":
        channel = "sms"
        properties = db.scalars(select(m.Property).join(m.Unit, m.Unit.property_id == m.Property.id)
            .join(m.Lease, m.Lease.unit_id == m.Unit.id).where(m.Lease.tenant_id == user.id,
                m.Lease.status.in_(("pending", "active")))).all()
        if not any(len(prefs.available_channels(prefs.policy_for(db, prop.landlord_id), prop.id)) > 1
                   for prop in properties):
            raise HTTPException(409, "Your landlord must enable a mobile channel before phone verification")
        try:
            contact = normalize_sa_phone(body.phone or user.phone or "")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    row = db.get(m.NotificationContactVerification, (user.id, kind), with_for_update=True)
    now = m.utcnow()
    if row and now - row.requested_at < timedelta(minutes=1):
        raise HTTPException(429, "Wait one minute before requesting another code")
    simulated = prefs.demo_mode()
    sender = None if simulated else build_sender(channel)
    if isinstance(sender, ConsoleSender):
        raise HTTPException(503, "Verification delivery is not configured")
    code = f"{secrets.randbelow(1_000_000):06}"
    if row is None:
        row = m.NotificationContactVerification(user_id=user.id, kind=kind)
        db.add(row)
    if row.contact != contact:
        row.verified_at = None
    row.contact = contact
    row.digest = code_digest(user.id, kind, contact, code)
    row.requested_at = now
    row.attempts = 0
    db.commit()
    if sender is not None:
        try:
            send_with_retries(sender, contact, "LandKeep verification code", f"Your LandKeep code is {code}. It expires in 10 minutes.")
        except Exception as exc:
            raise HTTPException(503, "Could not deliver the verification code") from exc
    return {"demo_code": code} if simulated else {"status": "sent"}


@router.post("/verify/{kind}/confirm")
def confirm_code(kind: Literal["email", "phone"], body: ContactCode,
                 user=Depends(require_tenant), db: Session = Depends(get_db)):
    row = db.get(m.NotificationContactVerification, (user.id, kind), with_for_update=True)
    now = m.utcnow()
    if not row or not row.digest or row.attempts >= 5 or now - row.requested_at > timedelta(minutes=10):
        raise HTTPException(400, "Request a new verification code")
    row.attempts += 1
    if not hmac.compare_digest(row.digest, code_digest(user.id, kind, row.contact, body.code)):
        db.commit()
        raise HTTPException(400, "Incorrect verification code")
    row.digest = None
    row.verified_at = now
    if kind == "phone":
        user.phone = row.contact
    db.commit()
    return {"status": "verified"}


@router.get("/inbox")
def get_inbox(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.Notification).where(m.Notification.user_id == user.id,
        m.Notification.channel == "in_app").order_by(m.Notification.id.desc()).limit(100))
    return [{"id": row.id, "subject": row.subject, "body": row.body, "created_at": row.created_at} for row in rows]


def unsubscribe_identity(token):
    try:
        tenant, agency, _ = token.split(".")
        tenant_id, agency_id = int(tenant), int(agency)
        if hmac.compare_digest(token, prefs.unsubscribe_token(tenant_id, agency_id)):
            return tenant_id, agency_id
    except (ValueError, TypeError):
        pass
    raise HTTPException(404, "Unsubscribe link not found")


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def confirm_unsubscribe(token: str):
    unsubscribe_identity(token)
    return '<h1>Unsubscribe from rent reminder emails</h1><form method="post"><button>Unsubscribe</button></form>'


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_email(token: str, db: Session = Depends(get_db)):
    tenant_id, agency_id = unsubscribe_identity(token)
    tenant = db.get(m.User, tenant_id)
    if tenant:
        prefs.unsubscribe(db, tenant, "email", agency_id)
        db.commit()
    return "<h1>Email reminders turned off</h1><p>Your LandKeep inbox stays available.</p>"


class Policy(BaseModel):
    reminders_enabled: bool = True
    sms: bool = False
    whatsapp: bool = False
    monthly_message_cap: int = Field(default=0, ge=0, le=1000000)
    offsets: list[Annotated[int, Field(ge=-31, le=31)]] = Field(
        default_factory=lambda: list(prefs.DEFAULT_OFFSETS), min_length=1, max_length=20)
    steps: dict[str, list[Channel]] = Field(default_factory=dict)
    template: str = Field(default="", max_length=600)
    properties: dict[str, dict[Literal["sms", "whatsapp"], bool]] = Field(default_factory=dict)

    @field_validator("template")
    @classmethod
    def validate_template(cls, value):
        allowed = {"tenant_name", "amount", "due_date", "unit", "property"}
        if any(name is not None and (name not in allowed or spec or conversion)
               for _, name, spec, conversion in Formatter().parse(value)):
            raise ValueError("Use only the documented template variables")
        return value


@router.get("/settings")
def get_policy(user=Depends(require_landlord), db: Session = Depends(get_db)):
    policy = prefs.policy_for(db, user.id)
    return Policy(**policy)


@router.get("/properties")
def policy_properties(user=Depends(require_landlord), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.Property).where(m.Property.landlord_id == user.id).order_by(m.Property.name))
    return [{"id": row.id, "name": row.name} for row in rows]


@router.put("/settings")
def put_policy(body: Policy, user=Depends(require_landlord), db: Session = Depends(get_db)):
    property_ids = set(db.scalars(select(m.Property.id).where(m.Property.landlord_id == user.id)))
    if not set(body.properties).issubset({str(property_id) for property_id in property_ids}):
        raise HTTPException(404, "Property not found")
    row = db.scalar(select(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == user.id))
    if row is None:
        row = m.AgencyReminderSettings(agency_id=user.id)
        db.add(row)
    previous = row.lease_notification_policy or {}
    updated = {**previous, **body.model_dump()}
    for channel in prefs.PAID_CHANNELS:
        rows = db.execute(select(m.Lease, m.Property).join(m.Unit, m.Unit.id == m.Lease.unit_id)
            .join(m.Property, m.Property.id == m.Unit.property_id).join(m.LeaseNotificationPreference,
                m.LeaseNotificationPreference.lease_id == m.Lease.id).where(m.Property.landlord_id == user.id,
                m.Lease.status.in_(("pending", "active")), m.LeaseNotificationPreference.channel == channel,
                m.LeaseNotificationPreference.enabled.is_(True)))
        for lease, prop in rows:
            if (channel in prefs.available_channels(previous, prop.id)
                    and channel not in prefs.available_channels(updated, prop.id)):
                prefs.save_choice(db, lease, user.id, channel, False, user.id, "landlord")
                db.flush()
                remaining = prefs.choices(db, lease)
                if (not any(remaining[item] for item in prefs.available_channels(updated, prop.id))
                        and prefs.verified(db, db.get(m.User, lease.tenant_id), "email")):
                    prefs.save_choice(db, lease, user.id, "email", True, user.id, "fallback")
                prefs.inbox(db, lease.tenant_id, "Reminder channel disabled",
                            f"Your landlord disabled {channel} for {prop.name}. Your inbox stays available.",
                            "reminder_channel_disabled")
    row.lease_notification_policy = updated
    db.commit()
    return body


class Pause(BaseModel):
    paused: bool


@router.put("/leases/{lease_id}/pause")
def pause_lease(lease_id: int, body: Pause, user=Depends(require_landlord), db: Session = Depends(get_db)):
    lease, _ = lease_context(db, lease_id, user)
    lease.reminders_paused = body.paused
    db.commit()
    return body


@router.get("/usage")
def usage(user=Depends(require_landlord), db: Session = Depends(get_db)):
    today = local_today()
    rows = db.scalars(select(m.AutomationMessage).where(m.AutomationMessage.agency_id == user.id,
        m.AutomationMessage.created_at >= today.replace(day=1), m.AutomationMessage.direction == "outbound"))
    counts, estimated = {}, {}
    for row in rows:
        if row.status in {"sent", "delivered", "read"}:
            counts[row.channel] = counts.get(row.channel, 0) + 1
        if row.cost_currency and row.cost_estimate is not None:
            estimated[row.cost_currency] = estimated.get(row.cost_currency, 0) + row.cost_estimate
    cap = prefs.policy_for(db, user.id).get("monthly_message_cap", 0)
    used = prefs.paid_usage(db, user.id, today.replace(day=1))
    return {"counts": counts, "estimated": estimated, "cap": cap, "used": used,
            "percentage": round(used * 100 / cap, 1) if cap else 0}


@router.get("/cost-preview")
def cost_preview(user=Depends(require_landlord), db: Session = Depends(get_db)):
    today = local_today()
    counts, estimated = {}, {}
    for offset in range(30):
        day = today + timedelta(days=offset)
        result = run_reminders(db, agency_id=user.id, day=day, dry_run=True, lease_schedule=True)
        for reminder in result["reminders"]:
            for outcome in reminder["channels"]:
                channel = outcome["channel"]
                if channel not in prefs.PAID_CHANNELS or outcome["status"] != "would_send":
                    continue
                counts[channel] = counts.get(channel, 0) + 1
                price = prefs.price_for(db, channel, day)
                if price:
                    estimated[price.currency] = estimated.get(price.currency, 0) + price.cost_per_message
    return {"counts": counts, "estimated": estimated, "demo": prefs.demo_mode()}
