"""Month-end rent reminders, using the existing lease, charge, and payment records."""
from __future__ import annotations

import os
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m

TIMEZONE_NAME = os.getenv("LANDKEEP_REMINDER_TIMEZONE", "Africa/Johannesburg")
REMINDER_WINDOWS = tuple(sorted({int(v.strip()) for v in os.getenv(
    "LANDKEEP_REMINDER_DAYS", "7,3,1,0").split(",") if v.strip()}, reverse=True))
SEND_TIME = os.getenv("LANDKEEP_REMINDER_SEND_TIME", "08:00")


def days_until_month_end(day: date) -> int:
    """Number of calendar days from `day` until the final day of its month."""
    return (date(day.year, day.month, monthrange(day.year, day.month)[1]) - day).days


def local_now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE_NAME))


def month_period(day: date) -> date:
    return day.replace(day=1)


def due_date_for_month(due_day: int, period: date) -> date:
    """Clamp lease due days to short months (including February)."""
    return date(period.year, period.month, min(due_day, monthrange(period.year, period.month)[1]))


@dataclass(frozen=True)
class ReminderCandidate:
    lease: m.Lease
    tenant: m.User
    unit: m.Unit
    property: m.Property
    period: date
    due_date: date
    amount_outstanding: float


def find_unpaid_active_leases(db: Session, day: date) -> list[ReminderCandidate]:
    """Return active leases overlapping this month with rent still outstanding."""
    period = month_period(day)
    month_end = date(period.year, period.month, monthrange(period.year, period.month)[1])
    stmt = (
        select(m.Lease, m.User, m.Unit, m.Property)
        .join(m.User, m.User.id == m.Lease.tenant_id)
        .join(m.Unit, m.Unit.id == m.Lease.unit_id)
        .join(m.Property, m.Property.id == m.Unit.property_id)
        .where(
            m.Lease.status == "active",
            m.Lease.start_date <= month_end,
            m.Lease.end_date >= period,
        )
        .order_by(m.Lease.id)
    )
    candidates = []
    for lease, tenant, unit, prop in db.execute(stmt):
        charge = db.scalar(select(m.RentCharge).where(
            m.RentCharge.lease_id == lease.id, m.RentCharge.period == period
        ).order_by(m.RentCharge.id.desc()).limit(1))
        paid = 0.0
        if charge is not None:
            paid = float(db.scalar(select(func.coalesce(func.sum(m.Payment.amount), 0.0)).where(
                m.Payment.charge_id == charge.id
            )) or 0)
        amount_due = float(charge.amount_due if charge is not None else lease.monthly_rent)
        outstanding = max(0.0, round(amount_due - paid, 2))
        if outstanding:
            due_date = charge.due_date if charge is not None else due_date_for_month(lease.due_day, period)
            if period <= lease.start_date <= month_end and due_date < lease.start_date:
                due_date = lease.start_date
            candidates.append(ReminderCandidate(
                lease=lease, tenant=tenant, unit=unit, property=prop, period=period,
                due_date=due_date,
                amount_outstanding=outstanding,
            ))
    return candidates


TEMPLATES = {
    "early": ("Rent reminder", "Hi {name}, a friendly reminder that {amount} remains outstanding for "
              "{property} / unit {unit}. Rent is due {due_date}; {days_remaining} days remain in this month."),
    "soon": ("Rent due soon", "Hi {name}, {amount} is still outstanding for {property} / unit {unit}. "
             "Please arrange payment by {due_date}; only {days_remaining} days remain in this month."),
    "last_day": ("Rent due today", "Hi {name}, {amount} remains outstanding for {property} / unit {unit}. "
                "Please arrange payment today ({due_date}). This is the last day of the month."),
}


def render_message(candidate: ReminderCandidate, days_remaining: int) -> tuple[str, str]:
    tone = "last_day" if days_remaining == 0 else "soon" if days_remaining <= 3 else "early"
    subject, template = TEMPLATES[tone]
    return subject, template.format(
        name=candidate.tenant.full_name.split()[0],
        amount=f"R {candidate.amount_outstanding:,.2f}",
        property=candidate.property.name,
        unit=candidate.unit.unit_number,
        due_date=f"{candidate.due_date.day} {candidate.due_date:%B %Y}",
        days_remaining=days_remaining,
    )


class Sender:
    channel = "console"

    def send(self, recipient: str, subject: str, message: str) -> None:
        raise NotImplementedError


class ConsoleSender(Sender):
    def send(self, recipient: str, subject: str, message: str) -> None:
        print(f"[RENT REMINDER -> {recipient}] {subject}: {message}")


def run_reminders(
    db: Session,
    *,
    day: date | None = None,
    dry_run: bool = False,
    window_days: int | None = None,
    windows: tuple[int, ...] = REMINDER_WINDOWS,
    sender: Sender | None = None,
) -> dict:
    day = day or local_now().date()
    actual_days_remaining = days_until_month_end(day)
    window = window_days if window_days is not None else actual_days_remaining
    days_remaining = window if window_days is not None and dry_run else actual_days_remaining
    if window_days is None and window not in windows:
        return {"period": month_period(day).isoformat(), "window_days": None,
                "dry_run": dry_run, "reminders": []}

    sender = sender or ConsoleSender()
    period = month_period(day)
    reminders = []
    for candidate in find_unpaid_active_leases(db, day):
        existing = db.scalar(select(m.RentReminderLog.id).where(
            m.RentReminderLog.lease_id == candidate.lease.id,
            m.RentReminderLog.period == period,
            m.RentReminderLog.window_days == window,
        ))
        if existing:
            continue

        subject, message = render_message(candidate, days_remaining)
        contact = candidate.tenant.email or candidate.tenant.phone
        item = {
            "tenant_id": candidate.tenant.id,
            "tenant": candidate.tenant.full_name,
            "lease_id": candidate.lease.id,
            "property": candidate.property.name,
            "unit": candidate.unit.unit_number,
            "period": period.isoformat(),
            "window_days": window,
            "amount_outstanding": candidate.amount_outstanding,
            "due_date": candidate.due_date.isoformat(),
            "days_remaining": days_remaining,
            "status": "would_send" if contact else "skipped: no contact",
            "channel": sender.channel if contact else "none",
            "subject": subject,
            "message": message,
        }
        reminders.append(item)
        if dry_run:
            continue

        log = m.RentReminderLog(
            tenant_id=candidate.tenant.id, lease_id=candidate.lease.id, period=period,
            window_days=window, channel=sender.channel if contact else "none",
            status="pending" if contact else "skipped: no contact",
            sent_at=None if contact else datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(log)
        try:
            db.commit()  # reserve the unique lease/month/window before delivery
        except IntegrityError:
            # A concurrent scheduler/manual run already reserved this window.
            db.rollback()
            continue
        if contact:
            try:
                sender.send(contact, subject, message)
                log.status = "sent"
                log.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
                item["status"] = "sent"
                db.commit()
            except Exception:
                log.status = "failed"
                db.commit()
                item["status"] = "failed"

    return {"period": period.isoformat(), "window_days": window,
            "dry_run": dry_run, "reminders": reminders}


def configured_send_time() -> time:
    hour_text, minute_text = SEND_TIME.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))
