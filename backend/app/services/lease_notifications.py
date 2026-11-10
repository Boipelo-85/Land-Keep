"""Lease-scoped preferences, contact checks and tenant inbox entries."""
import os
import hashlib
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update

from .. import models as m
from ..security import SECRET, is_fixture_account
from .automation_channels import channel_mode, deliver
from .reminder_senders import ConsoleSender

EXTERNAL_CHANNELS = ("email", "sms", "whatsapp")
PAID_CHANNELS = ("sms", "whatsapp")
DEFAULT_OFFSETS = (3, 1, 0, -1, -3, -7)
PAID_OFFSETS = (3, 0, -3)


def demo_mode():
    return os.getenv("LANDKEEP_DEMO_MODE", "").lower() == "true"


def policy_for(db, agency_id):
    settings = db.scalar(select(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == agency_id))
    return (settings.lease_notification_policy or {}) if settings else {}


def available_channels(policy, property_id):
    override = policy.get("properties", {}).get(str(property_id), {})
    return ("email", *(channel for channel in PAID_CHANNELS if override.get(channel, policy.get(channel, False))))


def contact_kind(channel):
    return "email" if channel == "email" else "phone"


def verified(db, tenant, channel):
    kind = contact_kind(channel)
    contact = getattr(tenant, kind)
    if not contact:
        return False
    if demo_mode():
        return True
    row = db.get(m.NotificationContactVerification, (tenant.id, kind))
    return bool(row and row.verified_at and row.contact == contact)


def choices(db, lease):
    rows = db.scalars(select(m.LeaseNotificationPreference).where(
        m.LeaseNotificationPreference.lease_id == lease.id,
        m.LeaseNotificationPreference.tenant_id == lease.tenant_id,
    ))
    values = {row.channel: row.enabled for row in rows}
    return {channel: values.get(channel, channel == "email") for channel in EXTERNAL_CHANNELS}


def inbox(db, user_id, subject, body, template):
    db.add(m.Notification(user_id=user_id, channel="in_app", template=template,
                          subject=subject, body=body, status="delivered"))


def save_choice(db, lease, agency_id, channel, enabled, actor_id, source):
    row = db.get(m.LeaseNotificationPreference, (lease.id, channel))
    if row is None:
        row = m.LeaseNotificationPreference(lease_id=lease.id, tenant_id=lease.tenant_id, channel=channel)
        db.add(row)
    row.enabled = enabled
    row.updated_by = actor_id
    row.source = source
    row.updated_at = m.utcnow()
    db.add(m.AutomationMessage(agency_id=agency_id, tenant_id=lease.tenant_id, kind="preference_changed",
        channel=channel, direction="internal", mode="audit", subject="Reminder preference changed",
        body=f"Lease {lease.id}: {channel} {'enabled' if enabled else 'disabled'} by {source}.", status="recorded"))


def price_for(db, channel, day):
    return db.scalar(select(m.ChannelCost).where(m.ChannelCost.channel == channel,
        m.ChannelCost.effective_from <= day).order_by(m.ChannelCost.effective_from.desc()).limit(1))


def paid_usage(db, agency_id, start):
    return db.scalar(select(func.count(m.AutomationMessage.id)).where(
        m.AutomationMessage.agency_id == agency_id, m.AutomationMessage.created_at >= start,
        m.AutomationMessage.cost_estimate.is_not(None), m.AutomationMessage.billable.is_(True),
        m.AutomationMessage.status != "skipped")) or 0


def claim_paid_budget(db, agency_id, channel, day):
    # The update takes a database write lock before counting reservations.
    db.execute(update(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == agency_id)
        .values(updated_at=m.AgencyReminderSettings.updated_at))
    policy = policy_for(db, agency_id)
    cap = policy.get("monthly_message_cap", 0)
    price = price_for(db, channel, day)
    start = day.replace(day=1)
    usage = paid_usage(db, agency_id, start)
    if usage >= cap:
        return None, "cap reached"
    if price is None:
        return None, "price not configured"
    for threshold in (80, 100):
        if usage * 100 < cap * threshold <= (usage + 1) * 100:
            inbox(db, agency_id, "Messaging cap alert",
                  f"Paid messages reached {threshold}% of the monthly cap of {cap}.", "messaging_cap")
    return price, None


def unsubscribe(db, tenant, channel, agency_id=None):
    query = select(m.Lease, m.Property).select_from(m.Lease).join(m.Unit, m.Unit.id == m.Lease.unit_id)
    query = query.join(m.Property, m.Property.id == m.Unit.property_id).where(
        m.Lease.tenant_id == tenant.id, m.Lease.status.in_(("pending", "active")))
    if agency_id is not None:
        query = query.where(m.Property.landlord_id == agency_id)
    changed = False
    for lease, prop in db.execute(query):
        selected = choices(db, lease)
        if not selected[channel]:
            continue
        changed = True
        save_choice(db, lease, prop.landlord_id, channel, False, tenant.id, "unsubscribe")
        remaining = any(selected[item] for item in available_channels(policy_for(db, prop.landlord_id), prop.id)
                        if item != channel)
        if not remaining and channel != "email" and verified(db, tenant, "email"):
            save_choice(db, lease, prop.landlord_id, "email", True, tenant.id, "fallback")
        elif not remaining:
            inbox(db, prop.landlord_id, "Tenant has no external reminder channel",
                  f"{tenant.full_name} opted out of {channel}. Their notices remain available in the inbox.",
                  "reminder_contact_missing")
    if changed:
        inbox(db, tenant.id, "Reminder preferences updated", f"You opted out of {channel}. Your inbox stays available.",
              "reminder_opt_out")


def unsubscribe_token(tenant_id, agency_id):
    data = f"{tenant_id}.{agency_id}"
    digest = hmac.new(SECRET.encode(), f"rent-email-optout:{data}".encode(), hashlib.sha256).hexdigest()
    return f"{data}.{digest}"


def email_optout_link(tenant_id, agency_id):
    base = os.getenv("LANDKEEP_NOTIFICATION_PUBLIC_API_URL", "").rstrip("/")
    if not base.startswith("https://"):
        return ""
    return f"{base}/lease-notifications/unsubscribe/{unsubscribe_token(tenant_id, agency_id)}"


def send_lease_notice(db, lease, prop, tenant, template, subject, body, *, request_id=None, formal=False):
    """Share the inbox, verified preferences and paid budget with non-rent lease notices."""
    inbox(db, tenant.id, subject, body, template)
    db.add(m.AutomationMessage(agency_id=prop.landlord_id, tenant_id=tenant.id, kind=template,
        channel="in_app", direction="outbound", mode="internal", subject=subject, body=body,
        request_id=request_id, status="delivered", billable=False))
    policy = policy_for(db, prop.landlord_id)
    selected = choices(db, lease)
    simulated = demo_mode()
    agency = db.get(m.User, prop.landlord_id)
    fixture = is_fixture_account(tenant.email) or is_fixture_account(agency.email)
    clock = datetime.now(ZoneInfo(os.getenv("LANDKEEP_REMINDER_TIMEZONE", "Africa/Johannesburg")))
    for channel in available_channels(policy, prop.id):
        if not selected[channel] and not (formal and channel == "email"):
            continue
        paid = channel in PAID_CHANNELS
        mode = "log" if simulated else channel_mode(channel)
        billable = paid and mode != "log"
        reason, price = None, None
        if fixture and not simulated:
            reason = "demo account"
        elif not verified(db, tenant, channel):
            reason = f"unverified {contact_kind(channel)}"
        elif not simulated and not 7 <= clock.hour < 20:
            reason = "quiet hours"
        elif billable:
            price, reason = claim_paid_budget(db, prop.landlord_id, channel, clock.date())
        if reason:
            db.add(m.AutomationMessage(agency_id=prop.landlord_id, tenant_id=tenant.id, kind=template,
                channel=channel, direction="outbound", mode=mode, subject=subject, body=body,
                request_id=request_id, status="skipped", billable=billable, error=reason))
            continue
        text = body + (" Reply STOP to opt out." if paid else "")
        row = deliver(db, prop.landlord_id, tenant, template, channel, getattr(tenant, contact_kind(channel)),
                      subject, text, request_id=request_id, sender=ConsoleSender(channel) if simulated else None)
        if price:
            row.cost_estimate = price.cost_per_message
            row.cost_currency = price.currency
        db.flush()
