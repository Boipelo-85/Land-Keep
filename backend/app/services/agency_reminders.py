"""Agency-scoped rent reminder selection, templates, and channel orchestration."""
from __future__ import annotations

import os
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import phonenumbers
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .. import models as m
from .reminder_senders import Sender, build_sender, send_with_retries

TIMEZONE_NAME = os.getenv("LANDKEEP_REMINDER_TIMEZONE", "Africa/Johannesburg")
ALLOWED_CHANNELS = ("whatsapp", "sms", "email")


def days_until_month_end(day: date) -> int:
    return (date(day.year, day.month, monthrange(day.year, day.month)[1]) - day).days


def local_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE_NAME)).date()


def normalize_sa_phone(phone: str) -> str:
    """Normalize a valid South African number to +27 E.164 or raise ValueError."""
    try:
        parsed = phonenumbers.parse(phone, "ZA")
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid South African phone number") from exc
    if not phonenumbers.is_valid_number(parsed) or phonenumbers.region_code_for_number(parsed) != "ZA":
        raise ValueError("Invalid South African phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


@dataclass(frozen=True)
class Candidate:
    agency: m.User
    tenant: m.User
    lease: m.Lease
    unit: m.Unit
    property: m.Property
    period: date
    due_date: date
    amount_outstanding: float


@dataclass(frozen=True)
class AgencyConfig:
    days: int = 3
    windows: tuple[int, ...] = (3,)
    channel_order: tuple[str, ...] = ("whatsapp", "sms", "email")
    strategy: str = "fallback"
    name: str = ""
    email: str = ""
    phone: str = ""


def _config(db: Session, agency: m.User) -> AgencyConfig:
    row = db.scalar(select(m.AgencyReminderSettings).where(
        m.AgencyReminderSettings.agency_id == agency.id
    ))
    days = row.reminder_days_before_month_end if row else 3
    windows = tuple(row.reminder_windows) if row and row.reminder_windows else (days,)
    configured_order = tuple(row.channel_order) if row and row.channel_order else ALLOWED_CHANNELS
    order = tuple(channel for channel in configured_order if channel in ALLOWED_CHANNELS)
    strategy = row.channel_strategy if row and row.channel_strategy in {"fallback", "all"} else "fallback"
    return AgencyConfig(
        days=days,
        windows=windows,
        channel_order=order or ALLOWED_CHANNELS,
        strategy=strategy,
        name=(row.agency_name if row and row.agency_name else agency.full_name),
        email=(row.contact_email if row and row.contact_email is not None else agency.email),
        phone=(row.contact_phone if row and row.contact_phone is not None else agency.phone or ""),
    )


def find_unpaid_active_leases(db: Session, day: date, agency_id: int | None = None) -> list[Candidate]:
    """Find unpaid current-month leases, optionally constrained to one agency."""
    period = day.replace(day=1)
    month_end = date(day.year, day.month, monthrange(day.year, day.month)[1])
    # Use explicit aliases so agency and tenant remain distinct User rows.
    agency_user = aliased(m.User, name="agency_user")
    tenant_user = aliased(m.User, name="tenant_user")
    statement = (
        select(agency_user, tenant_user, m.Lease, m.Unit, m.Property)
        .join(m.Property, m.Property.landlord_id == agency_user.id)
        .join(m.Unit, m.Unit.property_id == m.Property.id)
        .join(m.Lease, m.Lease.unit_id == m.Unit.id)
        .join(tenant_user, tenant_user.id == m.Lease.tenant_id)
        .where(
            agency_user.role == "landlord",
            m.Lease.status == "active",
            m.Lease.start_date <= month_end,
            m.Lease.end_date >= period,
        )
        .order_by(agency_user.id, m.Lease.id)
    )
    if agency_id is not None:
        statement = statement.where(agency_user.id == agency_id)

    found = []
    for agency, tenant, lease, unit, prop in db.execute(statement):
        charge = db.scalar(select(m.RentCharge).where(
            m.RentCharge.lease_id == lease.id, m.RentCharge.period == period
        ).order_by(m.RentCharge.id.desc()).limit(1))
        paid = 0.0 if charge is None else float(db.scalar(select(
            func.coalesce(func.sum(m.Payment.amount), 0.0)
        ).where(m.Payment.charge_id == charge.id)) or 0)
        due = float(charge.amount_due if charge is not None else lease.monthly_rent)
        outstanding = max(0.0, round(due - paid, 2))
        if outstanding <= 0:
            continue
        charge_due = charge.due_date if charge is not None else date(
            period.year, period.month, min(lease.due_day, monthrange(period.year, period.month)[1])
        )
        if period <= lease.start_date <= month_end and charge_due < lease.start_date:
            charge_due = lease.start_date
        found.append(Candidate(agency, tenant, lease, unit, prop, period, charge_due, outstanding))
    return found


MESSAGE_TEMPLATES = {
    "sms": ("Rent reminder from {agency}",
            "{agency}: {tenant}, {amount} outstanding for {property}/{unit}. Due {due}; {days} days left. "
            "Contact {agency_contact}. {opt_out}"),
    "whatsapp": ("Rent reminder from {agency}",
                 "{agency}: {tenant}, {amount} outstanding for {property}/{unit}. Due {due}; {days} days left. "
                 "Contact {agency_contact}. {opt_out}"),
    "email": ("Rent reminder: {property}, unit {unit}",
              "Hello {tenant},\n\nOur records show {amount} outstanding for {property}, unit {unit}.\n"
              "Due date: {due}\nDays remaining in the month: {days}\n\n"
              "Regards,\n{agency}\n{agency_contact}\n\n{opt_out}"),
}


def render_message(channel: str, candidate: Candidate, days_remaining: int, config: AgencyConfig):
    subject_template, body_template = MESSAGE_TEMPLATES[channel]
    agency_contact = " · ".join(part for part in (config.email, config.phone) if part) or "contact your property manager"
    opt_out = ("Reply STOP to unsubscribe" if channel in {"sms", "whatsapp"}
               else "Manage reminder preferences in your Land-Keep account to unsubscribe.")
    values = {
        "tenant": candidate.tenant.full_name,
        "amount": f"R {candidate.amount_outstanding:,.2f}",
        "property": candidate.property.name,
        "unit": candidate.unit.unit_number,
        "due": f"{candidate.due_date.day} {candidate.due_date:%B %Y}",
        "days": str(days_remaining),
        "agency": config.name,
        "agency_contact": agency_contact,
        "opt_out": opt_out,
    }
    subject = subject_template.format(**values)
    body = body_template.format(**values)
    whatsapp_variables = {
        "1": values["tenant"], "2": f'{values["property"]}, unit {values["unit"]}',
        "3": values["amount"], "4": values["due"], "5": values["days"],
        "6": values["agency"], "7": agency_contact, "8": opt_out,
    }
    return subject, body, whatsapp_variables


def _preference(db: Session, tenant_id: int) -> m.TenantChannelPreference | None:
    return db.scalar(select(m.TenantChannelPreference).where(
        m.TenantChannelPreference.tenant_id == tenant_id
    ))


def _contact(tenant: m.User, channel: str) -> tuple[str | None, str | None]:
    if channel in {"sms", "whatsapp"}:
        if not tenant.phone:
            return None, "no phone on file"
        try:
            return normalize_sa_phone(tenant.phone), None
        except ValueError as exc:
            return None, str(exc)
    if not tenant.email:
        return None, "no email on file"
    return tenant.email.strip(), None


def _existing(db: Session, candidate: Candidate, window: int, channel: str):
    return db.scalar(select(m.AgencyRentReminderLog).where(
        m.AgencyRentReminderLog.agency_id == candidate.agency.id,
        m.AgencyRentReminderLog.lease_id == candidate.lease.id,
        m.AgencyRentReminderLog.period == candidate.period,
        m.AgencyRentReminderLog.window_days == window,
        m.AgencyRentReminderLog.channel == channel,
    ))


def _write_log(db: Session, candidate: Candidate, window: int, channel: str,
               status: str, *, error: str | None = None, provider_message_id: str | None = None):
    row = m.AgencyRentReminderLog(
        agency_id=candidate.agency.id, tenant_id=candidate.tenant.id,
        lease_id=candidate.lease.id, period=candidate.period, window_days=window,
        channel=channel, status=status, provider_message_id=provider_message_id,
        error=error, sent_at=datetime.now(timezone.utc).replace(tzinfo=None) if status == "sent" else None,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return row


def _run_agency(db: Session, agency: m.User, day: date, dry_run: bool,
                window_override: int | None,
                sender_factory: Callable[[str], Sender]) -> list[dict]:
    config = _config(db, agency)
    actual_days_remaining = days_until_month_end(day)
    days_remaining = window_override if window_override is not None and dry_run else actual_days_remaining
    window = window_override if window_override is not None and dry_run else actual_days_remaining
    if window not in config.windows and window_override is None:
        return []
    outputs = []
    for candidate in find_unpaid_active_leases(db, day, agency_id=agency.id):
        preferences = _preference(db, candidate.tenant.id)
        opted_in = {
            "whatsapp": bool(preferences and preferences.whatsapp_opt_in),
            "sms": bool(preferences and preferences.sms_opt_in),
            "email": bool(preferences and preferences.email_opt_in),
        }
        selected = [channel for channel in config.channel_order if opted_in[channel]]
        if not selected:
            no_contact = not candidate.tenant.email and not candidate.tenant.phone
            status = "skipped"
            reason = "skipped: no contact" if no_contact else "skipped: no opted-in channel"
            output = {"agency_id": agency.id, "tenant_id": candidate.tenant.id,
                      "lease_id": candidate.lease.id, "period": candidate.period.isoformat(),
                      "window_days": window, "channels": [{"channel": "none", "status": reason}]}
            outputs.append(output)
            if not dry_run and not _existing(db, candidate, window, "none"):
                _write_log(db, candidate, window, "none", status, error=reason)
            continue

        prior_attempts = [
            _existing(db, candidate, window, channel) for channel in selected
        ]
        if config.strategy == "fallback" and any(
            row is not None and row.status in {"sent", "pending"} for row in prior_attempts
        ):
            continue
        if all(row is not None for row in prior_attempts):
            continue

        channel_results = []
        successful_before = False
        for channel in selected:
            if config.strategy == "fallback" and successful_before:
                break
            old = _existing(db, candidate, window, channel)
            if old:
                channel_results.append({"channel": channel, "status": old.status,
                                        "error": old.error, "already_attempted": True})
                if config.strategy == "fallback" and old.status == "sent":
                    successful_before = True
                continue

            contact, contact_error = _contact(candidate.tenant, channel)
            if contact_error and contact_error.startswith("no "):
                reason = f"skipped: no contact ({contact_error})"
                channel_results.append({"channel": channel, "status": "skipped", "error": reason})
                if not dry_run:
                    _write_log(db, candidate, window, channel, "skipped", error=reason)
                continue

            subject, body, variables = render_message(channel, candidate, days_remaining, config)
            if contact_error:
                channel_results.append({"channel": channel, "status": "failed", "error": contact_error})
                if not dry_run:
                    _write_log(db, candidate, window, channel, "failed", error=contact_error)
                continue
            if dry_run:
                channel_results.append({"channel": channel, "status": "would_send", "to": contact,
                                        "subject": subject, "message": body})
                if config.strategy == "fallback":
                    # Preview only the first available fallback channel.
                    break
                continue

            reserved = _write_log(db, candidate, window, channel, "pending",
                                  error="delivery reserved")
            if reserved is None:
                continue
            try:
                sender = sender_factory(channel)
                result = send_with_retries(sender, contact, subject, body,
                                           template_variables=variables)
                reserved.status = "sent"
                reserved.error = None
                reserved.provider_message_id = result.provider_message_id
                reserved.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                channel_results.append({"channel": channel, "status": "sent",
                                        "provider_message_id": result.provider_message_id})
                if config.strategy == "fallback":
                    successful_before = True
            except Exception as exc:
                reserved.status = "failed"
                reserved.error = str(exc)[:2000]
                db.commit()
                channel_results.append({"channel": channel, "status": "failed", "error": str(exc)})

        output = {"agency_id": agency.id, "tenant_id": candidate.tenant.id,
                  "lease_id": candidate.lease.id, "property": candidate.property.name,
                  "unit": candidate.unit.unit_number, "period": candidate.period.isoformat(),
                  "window_days": window, "amount_outstanding": candidate.amount_outstanding,
                  "due_date": candidate.due_date.isoformat(), "channels": channel_results}
        outputs.append(output)
    return outputs


def run_reminders(db: Session, *, agency_id: int | None = None, day: date | None = None,
                  dry_run: bool = False,
                  window_days: int | None = None,
                  sender_factory: Callable[[str], Sender] = build_sender) -> dict:
    day = day or local_today()
    if agency_id is None:
        active_agencies = db.scalars(
            select(m.Property.landlord_id).join(m.Unit, m.Unit.property_id == m.Property.id)
            .join(m.Lease, m.Lease.unit_id == m.Unit.id)
            .where(m.Lease.status == "active")
            .distinct()
        ).all()
    else:
        active_agencies = [agency_id]
    reminders = []
    for agency_key in active_agencies:
        agency = db.get(m.User, agency_key)
        if agency is None or agency.role != "landlord":
            continue
        reminders.extend(_run_agency(db, agency, day, dry_run, window_days, sender_factory))
    return {"period": day.replace(day=1).isoformat(), "dry_run": dry_run,
            "agency_id": agency_id, "reminders": reminders}
