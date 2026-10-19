from datetime import date, datetime

from sqlalchemy import select

from app import models as m
from app.database import SessionLocal
from app.services.agency_reminders import (
    days_until_month_end,
    find_unpaid_active_leases,
    run_reminders,
)
from app.services import reminder_senders
from app.services.reminder_senders import DeliveryResult
from app.security import hash_password
from conftest import auth


def test_month_end_calculation_including_february_leap_year_and_month_lengths():
    assert days_until_month_end(date(2023, 2, 28)) == 0
    assert days_until_month_end(date(2024, 2, 29)) == 0
    assert days_until_month_end(date(2024, 2, 22)) == 7
    assert days_until_month_end(date(2025, 4, 30)) == 0
    assert days_until_month_end(date(2025, 1, 31)) == 0


def _lease(db, unit, tenant, start=date(2024, 1, 1), end=date(2024, 12, 31), status="active"):
    lease = m.Lease(unit_id=unit.id, tenant_id=tenant.id, start_date=start, end_date=end,
                    monthly_rent=7000, deposit=7000, due_day=5, status=status)
    db.add(lease)
    db.flush()
    return lease


def _tenant(db, email, phone="082 555 0123", name="Reminder Tenant"):
    tenant = m.User(role="tenant", full_name=name, email=email, phone=phone, password_hash="x")
    db.add(tenant)
    db.flush()
    return tenant


def test_unpaid_query_is_agency_scoped_and_skips_paid(client):
    with SessionLocal() as db:
        first_agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        second_agency = db.scalar(select(m.User).where(m.User.email == "other@test.com"))
        first_unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        other_property = m.Property(landlord_id=second_agency.id, name="Other Agency House",
                                    address="2 Other Road", city="Pretoria")
        db.add(other_property)
        db.flush()
        other_unit = m.Unit(property_id=other_property.id, unit_number="B01", bedrooms=1,
                            monthly_rent=5000, status="occupied")
        db.add(other_unit)
        db.flush()

        partial_tenant = _tenant(db, "partial-agency@test.com")
        paid_tenant = _tenant(db, "paid-agency@test.com")
        other_tenant = _tenant(db, "other-agency@test.com")
        partial = _lease(db, first_unit, partial_tenant, start=date(2024, 2, 15), end=date(2024, 2, 25))
        paid = _lease(db, first_unit, paid_tenant)
        other = _lease(db, other_unit, other_tenant)
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

        found = find_unpaid_active_leases(db, date(2024, 2, 22), agency_id=first_agency.id)
        assert [item.lease.id for item in found] == [partial.id]
        assert found[0].amount_outstanding == 5000
        assert found[0].due_date == date(2024, 2, 15)  # due date cannot predate move-in
        all_agencies = find_unpaid_active_leases(db, date(2024, 2, 22))
        assert {item.agency.id for item in all_agencies} == {first_agency.id, second_agency.id}
        assert other.id in {item.lease.id for item in all_agencies}


def test_fallback_attempts_next_opted_in_channel_and_never_retries_channel(client, monkeypatch):
    monkeypatch.setenv("LANDKEEP_PROVIDER_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("LANDKEEP_PROVIDER_MIN_INTERVAL_SECONDS", "0")
    attempts = []

    class FakeSender:
        def __init__(self, channel):
            self.channel = channel

        def send(self, recipient, subject, message, *, template_variables=None):
            attempts.append(self.channel)
            if self.channel == "whatsapp":
                raise RuntimeError("mock WhatsApp failure")
            return DeliveryResult(provider_message_id=f"fake-{self.channel}")

    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = _tenant(db, "fallback@test.com")
        lease = _lease(db, unit, tenant)
        db.add(m.TenantChannelPreference(tenant_id=tenant.id, whatsapp_opt_in=True,
                                         sms_opt_in=True, email_opt_in=True))
        db.add(m.AgencyReminderSettings(agency_id=agency.id, reminder_days_before_month_end=7,
                                        reminder_windows=[7], channel_order=["whatsapp", "sms", "email"],
                                        channel_strategy="fallback"))
        db.commit()

        dispatch = lambda channel: FakeSender(channel)
        first = run_reminders(db, agency_id=agency.id, day=date(2024, 2, 22),
                              dry_run=False, sender_factory=dispatch)
        second = run_reminders(db, agency_id=agency.id, day=date(2024, 2, 22),
                               dry_run=False, sender_factory=dispatch)
        assert attempts == ["whatsapp", "sms"]
        assert first["reminders"][0]["channels"][-1]["status"] == "sent"
        assert second["reminders"] == []
        rows = db.scalars(select(m.AgencyRentReminderLog).where(
            m.AgencyRentReminderLog.lease_id == lease.id
        )).all()
        assert {(r.channel, r.status) for r in rows} == {("whatsapp", "failed"), ("sms", "sent")}
        assert next(r for r in rows if r.channel == "sms").provider_message_id == "fake-sms"


def test_dry_run_lists_only_consented_channels_and_does_not_write_logs(client):
    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = _tenant(db, "dryrun@test.com")
        lease = _lease(db, unit, tenant)
        db.add(m.TenantChannelPreference(tenant_id=tenant.id, sms_opt_in=True, email_opt_in=True))
        db.add(m.AgencyReminderSettings(agency_id=agency.id, reminder_days_before_month_end=7,
                                        reminder_windows=[7], channel_order=["whatsapp", "sms", "email"],
                                        channel_strategy="fallback"))
        db.commit()
        result = run_reminders(db, agency_id=agency.id, day=date(2024, 2, 22), dry_run=True)
        channels = result["reminders"][0]["channels"]
        assert [entry["channel"] for entry in channels] == ["sms"]
        assert channels[0]["status"] == "would_send"
        assert db.scalar(select(m.AgencyRentReminderLog.id).where(
            m.AgencyRentReminderLog.lease_id == lease.id
        )) is None


def test_invalid_sa_phone_is_logged_failed_then_falls_back_to_email(client, monkeypatch):
    monkeypatch.setenv("LANDKEEP_PROVIDER_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("LANDKEEP_PROVIDER_MIN_INTERVAL_SECONDS", "0")
    sent = []

    class EmailSender:
        channel = "email"

        def send(self, recipient, subject, message, *, template_variables=None):
            sent.append(recipient)
            return DeliveryResult("email-id")

    class NeverPhoneSender:
        channel = "sms"

        def send(self, *args, **kwargs):
            raise AssertionError("invalid numbers must not reach a provider")

    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = _tenant(db, "invalid-phone@test.com", phone="not a phone")
        lease = _lease(db, unit, tenant)
        db.add(m.TenantChannelPreference(tenant_id=tenant.id, sms_opt_in=True, email_opt_in=True))
        db.add(m.AgencyReminderSettings(agency_id=agency.id, reminder_days_before_month_end=7,
                                        reminder_windows=[7], channel_order=["sms", "email"],
                                        channel_strategy="fallback"))
        db.commit()

        result = run_reminders(
            db, agency_id=agency.id, day=date(2024, 2, 22), dry_run=False,
            sender_factory=lambda channel: NeverPhoneSender() if channel == "sms" else EmailSender(),
        )
        assert sent == [tenant.email]
        rows = db.scalars(select(m.AgencyRentReminderLog).where(
            m.AgencyRentReminderLog.lease_id == lease.id
        )).all()
        assert {r.channel: r.status for r in rows} == {"sms": "failed", "email": "sent"}
        assert result["reminders"][0]["channels"][-1]["status"] == "sent"


def test_no_contact_is_skipped_and_recorded(client):
    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = _tenant(db, "no-contact@test.com", phone=None)
        tenant.email = ""
        lease = _lease(db, unit, tenant)
        db.add(m.TenantChannelPreference(tenant_id=tenant.id, sms_opt_in=True))
        db.add(m.AgencyReminderSettings(agency_id=agency.id, reminder_days_before_month_end=7,
                                        reminder_windows=[7], channel_order=["sms"],
                                        channel_strategy="fallback"))
        db.commit()

        result = run_reminders(db, agency_id=agency.id, day=date(2024, 2, 22), dry_run=False,
                               sender_factory=lambda _channel: (_ for _ in ()).throw(
                                   AssertionError("contactless reminder must not reach provider")))
        row = db.scalar(select(m.AgencyRentReminderLog).where(
            m.AgencyRentReminderLog.lease_id == lease.id
        ))
        assert row.status == "skipped"
        assert row.error.startswith("skipped: no contact")
        assert result["reminders"][0]["channels"][0]["status"] == "skipped"


def test_provider_retries_rate_limit_with_mocked_sender(monkeypatch):
    monkeypatch.setenv("LANDKEEP_PROVIDER_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LANDKEEP_PROVIDER_RETRY_BASE_SECONDS", "0")
    monkeypatch.setattr(reminder_senders, "_rate_limit", lambda: None)

    class Mock429(Exception):
        status = 429

    class RateLimitedSender:
        channel = "sms"

        def __init__(self):
            self.calls = 0

        def send(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise Mock429("Too many requests")
            return DeliveryResult("retried-message")

    sender = RateLimitedSender()
    result = reminder_senders.send_with_retries(sender, "+27825550123", "subject", "message")
    assert sender.calls == 2
    assert result.provider_message_id == "retried-message"


def test_manual_dry_run_is_landlord_only_and_uses_only_that_agency(client):
    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        tenant = m.User(role="tenant", full_name="Endpoint Tenant", email="endpoint@test.com",
                        phone="0825550123", password_hash=hash_password("password123"))
        db.add(tenant)
        db.flush()
        _lease(db, unit, tenant, start=date(2026, 1, 1), end=date(2027, 1, 1))
        db.add(m.TenantChannelPreference(tenant_id=tenant.id, sms_opt_in=True))
        db.commit()

    assert client.post("/reminders/run?dry_run=true&window_days=3").status_code == 401
    tenant_headers = auth(client, "endpoint@test.com")
    assert client.post("/reminders/run?dry_run=true&window_days=3",
                       headers=tenant_headers).status_code == 403
    landlord_headers = auth(client, "landlord@test.com")
    preview = client.post("/reminders/run?dry_run=true&window_days=3",
                          headers=landlord_headers)
    assert preview.status_code == 200
    reminders = preview.json()["reminders"]
    assert len(reminders) == 1
    assert reminders[0]["agency_id"] == agency.id
    assert reminders[0]["tenant_id"] == tenant.id
    assert reminders[0]["channels"][0]["status"] == "would_send"
