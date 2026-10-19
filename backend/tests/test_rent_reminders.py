from datetime import date, datetime

from sqlalchemy import select

from app import models as m
from app.database import SessionLocal
from app.services.rent_reminders import days_until_month_end, find_unpaid_active_leases, run_reminders


def test_days_until_month_end_handles_month_lengths_and_leap_years():
    assert days_until_month_end(date(2023, 2, 21)) == 7  # February 28
    assert days_until_month_end(date(2023, 2, 28)) == 0
    assert days_until_month_end(date(2024, 2, 22)) == 7  # leap day February 29
    assert days_until_month_end(date(2024, 2, 29)) == 0
    assert days_until_month_end(date(2025, 4, 27)) == 3  # 30-day month
    assert days_until_month_end(date(2025, 4, 30)) == 0
    assert days_until_month_end(date(2025, 1, 30)) == 1  # 31-day month
    assert days_until_month_end(date(2025, 1, 31)) == 0


def _add_lease(db, unit, tenant, *, start, end, status="active"):
    lease = m.Lease(
        unit_id=unit.id, tenant_id=tenant.id, start_date=start, end_date=end,
        monthly_rent=7000, deposit=7000, due_day=5, status=status,
    )
    db.add(lease)
    db.flush()
    return lease


def test_unpaid_query_includes_partial_and_midmonth_leases_skips_paid(client):
    with SessionLocal() as db:
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        partial_tenant = m.User(role="tenant", full_name="Partial Tenant", email="partial@test.com",
                                phone=None, password_hash="x")
        paid_tenant = m.User(role="tenant", full_name="Paid Tenant", email="paid@test.com",
                             phone="+27000", password_hash="x")
        ended_tenant = m.User(role="tenant", full_name="Ended Tenant", email="ended@test.com",
                              phone="+27001", password_hash="x")
        db.add_all([partial_tenant, paid_tenant, ended_tenant])
        db.flush()
        partial = _add_lease(db, unit, partial_tenant, start=date(2024, 2, 15), end=date(2024, 3, 10))
        paid = _add_lease(db, unit, paid_tenant, start=date(2024, 1, 1), end=date(2024, 12, 31))
        _add_lease(db, unit, ended_tenant, start=date(2024, 1, 1), end=date(2024, 2, 10), status="ended")
        partial_charge = m.RentCharge(lease_id=partial.id, period=date(2024, 2, 1),
                                      amount_due=7000, due_date=date(2024, 2, 5))
        paid_charge = m.RentCharge(lease_id=paid.id, period=date(2024, 2, 1),
                                   amount_due=7000, due_date=date(2024, 2, 5))
        db.add_all([partial_charge, paid_charge])
        db.flush()
        db.add_all([
            m.Payment(charge_id=partial_charge.id, amount=2000, paid_at=datetime(2024, 2, 10), method="eft"),
            m.Payment(charge_id=paid_charge.id, amount=7000, paid_at=datetime(2024, 2, 10), method="eft"),
        ])
        db.commit()

        found = find_unpaid_active_leases(db, date(2024, 2, 22))
        assert [c.lease.id for c in found] == [partial.id]
        assert found[0].amount_outstanding == 5000
        assert found[0].due_date == date(2024, 2, 15)


def test_reminder_window_is_logged_once_even_when_job_repeats(client):
    class RecordingSender:
        channel = "console"

        def __init__(self):
            self.messages = []

        def send(self, recipient, subject, message):
            self.messages.append((recipient, subject, message))

    sender = RecordingSender()
    with SessionLocal() as db:
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = m.User(role="tenant", full_name="Unpaid Tenant", email="unpaid@test.com",
                        phone=None, password_hash="x")
        db.add(tenant)
        db.flush()
        lease = _add_lease(db, unit, tenant, start=date(2024, 1, 1), end=date(2024, 12, 31))
        charge = m.RentCharge(lease_id=lease.id, period=date(2024, 2, 1),
                              amount_due=7000, due_date=date(2024, 2, 5))
        db.add(charge)
        db.commit()

        first = run_reminders(db, day=date(2024, 2, 22), window_days=7,
                              dry_run=False, sender=sender)
        second = run_reminders(db, day=date(2024, 2, 22), window_days=7,
                               dry_run=False, sender=sender)
        assert first["reminders"][0]["status"] == "sent"
        assert second["reminders"] == []
        assert len(sender.messages) == 1
        logs = db.scalars(select(m.RentReminderLog).where(
            m.RentReminderLog.lease_id == lease.id,
            m.RentReminderLog.period == date(2024, 2, 1),
            m.RentReminderLog.window_days == 7,
        )).all()
        assert len(logs) == 1
        assert logs[0].status == "sent"


def test_no_contact_is_logged_as_skipped(client):
    with SessionLocal() as db:
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = m.User(role="tenant", full_name="No Contact", email="", phone=None, password_hash="x")
        db.add(tenant)
        db.flush()
        lease = _add_lease(db, unit, tenant, start=date(2024, 1, 1), end=date(2024, 12, 31))
        db.commit()
        result = run_reminders(db, day=date(2024, 2, 22), window_days=7, dry_run=False)
        assert result["reminders"][0]["status"] == "skipped: no contact"
        log = db.scalar(select(m.RentReminderLog).where(m.RentReminderLog.lease_id == lease.id))
        assert log.status == "skipped: no contact"
