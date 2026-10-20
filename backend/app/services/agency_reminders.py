"""Agency-scoped rent reminder selection, templates, and channel orchestration."""
from __future__ import annotations

import os
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .. import models as m
from ..phone_numbers import normalize_sa_phone
from .reminder_senders import Sender, build_sender, send_with_retries

TIMEZONE_NAME = os.getenv("LANDKEEP_REMINDER_TIMEZONE", "Africa/Johannesburg")
ALLOWED_CHANNELS = ("whatsapp", "sms", "email")


def days_until_month_end(day: date) -> int:
    # A window of N days fires on (last calendar day - N days); e.g. Oct 31 - 3 = Oct 28.
    return (date(day.year, day.month, monthrange(day.year, day.month)[1]) - day).days


def local_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE_NAME)).date()


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
    strategy: str = "all"
    reminders_enabled: bool = True
    enabled_channels: tuple[str, ...] = ALLOWED_CHANNELS
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
    configured_enabled = row.enabled_channels if row and row.enabled_channels else ALLOWED_CHANNELS
    enabled = tuple(channel for channel in configured_enabled
                    if channel in ALLOWED_CHANNELS)
    strategy = row.channel_strategy if row and row.channel_strategy in {"fallback", "all"} else "all"
    return AgencyConfig(
        days=days,
        windows=windows,
        channel_order=order or ALLOWED_CHANNELS,
        strategy=strategy,
        reminders_enabled=row.reminders_enabled if row else True,
        enabled_channels=enabled,
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
            tenant_user.role == "tenant",
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


def render_message(channel: str, candidate: Candidate | list[Candidate], days_remaining: int,
                   config: AgencyConfig):
    candidates = candidate if isinstance(candidate, list) else [candidate]
    first = candidates[0]
    subject_template, body_template = MESSAGE_TEMPLATES[channel]
    agency_contact = " | ".join(part for part in (config.email, config.phone) if part) or "contact your property manager"
    opt_out = ("Reply STOP to unsubscribe" if channel in {"sms", "whatsapp"}
               else "Manage reminder preferences in your Land-Keep account to unsubscribe.")
    details = [
        f"{item.property.name}/{item.unit.unit_number}: R {item.amount_outstanding:,.2f} outstanding, "
        f"due {item.due_date.day} {item.due_date:%B %Y}"
        for item in candidates
    ]
    total = round(sum(item.amount_outstanding for item in candidates), 2)
    values = {
        "tenant": first.tenant.full_name,
        "amount": f"R {total:,.2f}",
        "property": first.property.name,
        "unit": first.unit.unit_number if len(candidates) == 1 else f"{len(candidates)} units",
        "due": f"{first.due_date.day} {first.due_date:%B %Y}",
        "days": str(days_remaining),
        "agency": config.name,
        "agency_contact": agency_contact,
        "opt_out": opt_out,
    }
    subject = subject_template.format(**values)
    if len(candidates) == 1:
        body = body_template.format(**values)
    elif channel == "email":
        body = (f"Hello {values['tenant']},\n\nOur records show the following outstanding rent:\n- "
                + "\n- ".join(details) + f"\n\nTotal outstanding: {values['amount']}\n"
                f"Days remaining in the month: {days_remaining}\n\nRegards,\n{config.name}\n"
                f"{agency_contact}\n\n{opt_out}")
    else:
        body = (f"{config.name}: {values['tenant']}, outstanding rent: "
                + "; ".join(details) + f". Total {values['amount']}; {days_remaining} days left. "
                f"Contact {agency_contact}. {opt_out}")
    whatsapp_variables = {
        "1": values["tenant"], "2": "; ".join(details),
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
               status: str, *, error: str | None = None, skip_reason: str | None = None,
               provider_message_id: str | None = None):
    row = m.AgencyRentReminderLog(
        agency_id=candidate.agency.id, tenant_id=candidate.tenant.id,
        lease_id=candidate.lease.id, period=candidate.period, window_days=window,
        channel=channel, status=status, skip_reason=skip_reason,
        provider_message_id=provider_message_id, error=error,
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None) if status == "sent" else None,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return row


def _reserve_batch(db: Session, candidates: list[Candidate], window: int,
                   channel: str) -> list[m.AgencyRentReminderLog] | None:
    """Atomically claim all lease rows backing one combined tenant/channel send."""
    rows = [m.AgencyRentReminderLog(
        agency_id=item.agency.id, tenant_id=item.tenant.id, lease_id=item.lease.id,
        period=item.period, window_days=window, channel=channel, status="pending",
    ) for item in candidates]
    db.add_all(rows)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return rows


def _tenant_consents(db: Session, tenant: m.User) -> dict[str, bool]:
    """Read the tenant columns; tolerate pre-migration preference rows in test/legacy data."""
    direct_values = {
        "whatsapp": bool(tenant.whatsapp_opt_in),
        "sms": bool(tenant.sms_opt_in),
        "email": bool(tenant.email_opt_in),
    }
    if tenant.consent_recorded_at is not None or any(direct_values.values()):
        return direct_values
    legacy = _preference(db, tenant.id)
    return {
        "whatsapp": bool(legacy and legacy.whatsapp_opt_in),
        "sms": bool(legacy and legacy.sms_opt_in),
        "email": bool(legacy and legacy.email_opt_in),
    }


def _eligible_windows(day: date, config: AgencyConfig, window_override: int | None,
                       dry_run: bool) -> list[int]:
    if not config.reminders_enabled:
        return []
    month_end = date(day.year, day.month, monthrange(day.year, day.month)[1])
    windows = [window_override] if window_override is not None and dry_run else config.windows
    if window_override is not None and dry_run:
        return windows if day <= month_end else []
    # A window N is due on (month end - N calendar days). It is eligible from
    # that date through the month's last day, which allows catch-up after downtime.
    return [window for window in windows
            if day >= month_end - timedelta(days=window) and day <= month_end]


def _run_agency(db: Session, agency: m.User, day: date, dry_run: bool,
                window_override: int | None,
                sender_factory: Callable[[str], Sender]) -> list[dict]:
    config = _config(db, agency)
    windows = _eligible_windows(day, config, window_override, dry_run)
    if not windows:
        return []

    candidates = find_unpaid_active_leases(db, day, agency_id=agency.id)
    grouped: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.tenant.id, []).append(candidate)

    outputs: list[dict] = []
    days_remaining = days_until_month_end(day)
    for window in windows:
        for tenant_candidates in grouped.values():
            tenant = tenant_candidates[0].tenant
            consent = _tenant_consents(db, tenant)
            selected = [channel for channel in config.channel_order
                        if channel in config.enabled_channels and consent[channel]]
            channel_results: list[dict] = []
            if not selected:
                has_contact = bool((tenant.phone and tenant.phone.strip()) or
                                   (tenant.email and tenant.email.strip()))
                reason = "no consent" if has_contact else "no contact"
                for item in tenant_candidates:
                    if _existing(db, item, window, "none") is None and not dry_run:
                        _write_log(db, item, window, "none", "skipped", skip_reason=reason)
                channel_results.append({"channel": "none", "status": "skipped", "skip_reason": reason,
                                        "lease_ids": [item.lease.id for item in tenant_candidates]})
                outputs.append(_tenant_output(agency, tenant_candidates, window, days_remaining,
                                              channel_results))
                continue

            successful_before = False
            for channel in selected:
                if config.strategy == "fallback" and successful_before:
                    break
                outstanding = [item for item in tenant_candidates
                               if _existing(db, item, window, channel) is None]
                if not outstanding:
                    prior = [_existing(db, item, window, channel) for item in tenant_candidates]
                    if config.strategy == "fallback" and any(row and row.status in {"sent", "pending"}
                                                               for row in prior):
                        successful_before = True
                    continue

                contact, contact_error = _contact(tenant, channel)
                if contact_error:
                    if contact_error.startswith("no "):
                        status, skip_reason = "skipped", "no contact"
                        err = f"skipped: no contact ({contact_error})"
                    else:
                        status, skip_reason, err = "failed", None, contact_error
                    channel_results.append({"channel": channel, "status": status,
                                            "error": err, "skip_reason": skip_reason,
                                            "lease_ids": [item.lease.id for item in outstanding]})
                    if not dry_run:
                        for item in outstanding:
                            _write_log(db, item, window, channel, status,
                                       error=err, skip_reason=skip_reason)
                    continue

                subject, body, variables = render_message(channel, outstanding, days_remaining, config)
                if dry_run:
                    channel_results.append({"channel": channel, "status": "would_send", "to": contact,
                                            "subject": subject, "message": body,
                                            "lease_ids": [item.lease.id for item in outstanding],
                                            "amount_outstanding": round(sum(
                                                item.amount_outstanding for item in outstanding), 2)})
                    if config.strategy == "fallback":
                        break
                    continue

                reserved = _reserve_batch(db, outstanding, window, channel)
                if reserved is None:
                    channel_results.append({"channel": channel, "status": "already_handled"})
                    if config.strategy == "fallback" and any(
                        (row := _existing(db, item, window, channel)) is not None and row.status in {"sent", "pending"}
                        for item in outstanding
                    ):
                        successful_before = True
                    continue
                try:
                    sender = sender_factory(channel)
                    result = send_with_retries(sender, contact, subject, body,
                                               template_variables=variables)
                    sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    for row in reserved:
                        row.status = "sent"
                        row.error = None
                        row.provider_message_id = result.provider_message_id
                        row.sent_at = sent_at
                    db.commit()
                    channel_results.append({"channel": channel, "status": "sent",
                                            "provider_message_id": result.provider_message_id,
                                            "lease_ids": [item.lease.id for item in outstanding],
                                            "amount_outstanding": round(sum(
                                                item.amount_outstanding for item in outstanding), 2)})
                    if config.strategy == "fallback":
                        successful_before = True
                except Exception as exc:
                    db.rollback()
                    for item in outstanding:
                        row = _existing(db, item, window, channel)
                        if row is not None and row.status == "pending":
                            row.status = "failed"
                            row.error = str(exc)[:2000]
                    db.commit()
                    channel_results.append({"channel": channel, "status": "failed", "error": str(exc)})

            if channel_results:
                outputs.append(_tenant_output(agency, tenant_candidates, window, days_remaining,
                                              channel_results))
    return outputs


def _tenant_output(agency: m.User, candidates: list[Candidate], window: int,
                   days_remaining: int, channels: list[dict]) -> dict:
    return {
        "agency_id": agency.id,
        "tenant_id": candidates[0].tenant.id,
        "lease_id": candidates[0].lease.id if len(candidates) == 1 else None,
        "lease_ids": [item.lease.id for item in candidates],
        "leases": [{"lease_id": item.lease.id, "property": item.property.name,
                    "unit": item.unit.unit_number,
                    "amount_outstanding": item.amount_outstanding,
                    "due_date": item.due_date.isoformat()} for item in candidates],
        "period": candidates[0].period.isoformat(),
        "window_days": window,
        "days_remaining": days_remaining,
        "amount_outstanding": round(sum(item.amount_outstanding for item in candidates), 2),
        "channels": channels,
    }

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
    agency_errors = []
    agencies_processed = 0
    for agency_key in active_agencies:
        agency = db.get(m.User, agency_key)
        if agency is None or agency.role != "landlord":
            continue
        try:
            reminders.extend(_run_agency(db, agency, day, dry_run, window_days, sender_factory))
            if _config(db, agency).reminders_enabled:
                agencies_processed += 1
        except Exception as exc:
            db.rollback()
            agency_errors.append({"agency_id": agency.id, "error": str(exc)[:1000]})

    channel_statuses = [channel for reminder in reminders for channel in reminder["channels"]]
    return {
        "period": day.replace(day=1).isoformat(),
        "dry_run": dry_run,
        "agency_id": agency_id,
        "reminders": reminders,
        "summary": {
            "agencies_processed": agencies_processed,
            "tenants_eligible": len({row["tenant_id"] for row in reminders}),
            "sent": sum(row.get("status") == "sent" for row in channel_statuses),
            "failed": sum(row.get("status") == "failed" for row in channel_statuses),
            "skipped": sum(row.get("status") == "skipped" for row in channel_statuses),
            "would_send": sum(row.get("status") == "would_send" for row in channel_statuses),
            "agency_errors": agency_errors,
        },
    }
