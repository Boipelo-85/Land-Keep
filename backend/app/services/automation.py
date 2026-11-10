"""Maintenance automation and live WhatsApp replies."""
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .. import models as m
from ..security import is_fixture_account
from .lease_notifications import inbox, send_lease_notice, unsubscribe
from .agency_reminders import _tenant_consents
from .automation_channels import CHANNELS, deliver

STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}


def tenant_messages(db, agency_id, tenant, kind, subject, body, *, request_id=None):
    request = db.get(m.MaintenanceRequest, request_id) if request_id else None
    if request:
        lease = db.scalar(select(m.Lease).where(m.Lease.tenant_id == tenant.id,
            m.Lease.unit_id == request.unit_id, m.Lease.status == "active").order_by(m.Lease.id.desc()).limit(1))
        prop = db.get(m.Property, db.get(m.Unit, request.unit_id).property_id)
        if lease and prop.landlord_id == agency_id:
            send_lease_notice(db, lease, prop, tenant, kind, subject, body, request_id=request_id)
            return
    inbox(db, tenant.id, subject, body, kind)
    preferences = _tenant_consents(db, tenant)
    settings = db.scalar(select(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == agency_id))
    order = settings.channel_order if settings else CHANNELS
    enabled = settings.enabled_channels if settings else CHANNELS
    for channel in order:
        if channel not in enabled or channel not in CHANNELS or not preferences[channel]:
            continue
        recipient = tenant.email if channel == "email" else tenant.phone
        text = body + (" Reply STOP to opt out." if channel in {"whatsapp", "sms"} else "")
        row = deliver(db, agency_id, tenant, kind, channel, recipient, subject, text, request_id=request_id)
        if row.status in {"sent", "delivered"} and (not settings or settings.channel_strategy == "fallback"):
            break


def acknowledge_request(db, agency, tenant, request):
    reference = f"MR-{request.id:06d}"
    tenant_messages(db, agency.id, tenant, "maintenance_received", f"Report {reference} received",
        f"We received your maintenance report {reference}. Expect an update within one business day.",
        request_id=request.id)
    deliver(db, agency.id, tenant, "maintenance_new", "email", agency.email,
        f"New maintenance report {reference}",
        f"{tenant.full_name} submitted a maintenance report. Review {reference} in LandKeep.",
        request_id=request.id)


def run_followups(db, now: datetime) -> int:
    requests = db.execute(select(m.MaintenanceRequest, m.Property.landlord_id)
        .join(m.Unit, m.Unit.id == m.MaintenanceRequest.unit_id)
        .join(m.Property, m.Property.id == m.Unit.property_id)
        .where(m.MaintenanceRequest.status == "resolved",
               m.MaintenanceRequest.resolved_at <= now - timedelta(hours=48))).all()
    count = 0
    for request, agency_id in requests:
        agency = db.get(m.User, agency_id)
        tenant = db.get(m.User, request.tenant_id)
        if not agency or not tenant or is_fixture_account(agency.email) or is_fixture_account(tenant.email):
            continue
        settings = db.scalar(select(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == agency_id))
        if settings and "whatsapp" not in settings.enabled_channels:
            continue
        if not tenant.phone or not _tenant_consents(db, tenant)["whatsapp"]:
            continue
        key = f"repair:real:{request.id}:{request.resolved_at.isoformat()}"
        if db.scalar(select(m.AutomationMessage.id).where(m.AutomationMessage.dedupe_key == key)):
            continue
        try:
            with db.begin_nested():
                row = deliver(db, agency_id, tenant, "maintenance_followup", "whatsapp", tenant.phone,
                    f"Repair check MR-{request.id:06d}",
                    f"Is repair MR-{request.id:06d} fixed? Reply 1 for yes, 2 for no, or STOP to opt out.",
                    request_id=request.id, dedupe_key=key)
                count += row.status in {"sent", "delivered"}
        except IntegrityError:
            continue
    db.commit()
    return count


def handle_inbound(db, agency_id, tenant, body, *, message_id, reply_to=None):
    """Record a reply once and apply its action in the same transaction."""
    keyword = body.strip().upper()
    channel, mode = "whatsapp", "real"
    row = m.AutomationMessage(agency_id=agency_id, tenant_id=tenant.id, kind="tenant_reply",
        channel=channel, direction="inbound", mode=mode, subject="", body=body, status="read",
        provider_message_id=message_id, dedupe_key=f"{mode}:in:{message_id}", read_at=m.utcnow())
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return "already_processed"
    if keyword in STOP_WORDS:
        unsubscribe(db, tenant, channel, agency_id)
        consents = _tenant_consents(db, tenant)
        preferences = db.scalar(select(m.TenantChannelPreference).where(
            m.TenantChannelPreference.tenant_id == tenant.id))
        if preferences is None:
            preferences = m.TenantChannelPreference(tenant_id=tenant.id)
            db.add(preferences)
        for name, opted_in in consents.items():
            value = opted_in and name != channel
            setattr(preferences, f"{name}_opt_in", value)
            setattr(tenant, f"{name}_opt_in", value)
        tenant.consent_recorded_at = preferences.updated_at = m.utcnow()
        tenant.consent_recorded_by = tenant.id
        return "opted_out"
    if keyword not in {"1", "2"} or channel != "whatsapp":
        return "recorded"
    statement = select(m.AutomationMessage).join(m.MaintenanceRequest,
        m.MaintenanceRequest.id == m.AutomationMessage.request_id).where(
        m.AutomationMessage.agency_id == agency_id, m.AutomationMessage.tenant_id == tenant.id,
        m.AutomationMessage.channel == channel, m.AutomationMessage.mode == mode,
        m.AutomationMessage.kind == "maintenance_followup",
        m.AutomationMessage.answered_at.is_(None),
        m.AutomationMessage.status.in_(("sent", "delivered", "read")),
        m.MaintenanceRequest.status == "resolved",
        m.MaintenanceRequest.resolved_at <= m.AutomationMessage.created_at)
    if reply_to:
        statement = statement.where(m.AutomationMessage.provider_message_id == reply_to)
    prompts = db.scalars(statement.order_by(m.AutomationMessage.id.desc()).limit(2)).all()
    if len(prompts) != 1:
        return "no_unambiguous_repair"
    prompt = prompts[0]
    claimed = db.execute(update(m.AutomationMessage).where(m.AutomationMessage.id == prompt.id,
        m.AutomationMessage.answered_at.is_(None)).values(answered_at=m.utcnow()))
    if not claimed.rowcount:
        return "already_processed"
    row.request_id = prompt.request_id
    request = db.get(m.MaintenanceRequest, prompt.request_id)
    if keyword == "2":
        request.status = "open"
        request.resolved_at = None
        if request.conversation_id:
            db.get(m.MaintenanceConversation, request.conversation_id).status = "escalated"
        return "reopened"
    return "confirmed"
