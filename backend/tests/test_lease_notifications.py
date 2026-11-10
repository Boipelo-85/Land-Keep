from datetime import date
from uuid import uuid4

from sqlalchemy import select

from app import models as m
from app.database import SessionLocal
from app.services import agency_reminders
from app.services.lease_notifications import save_choice
from app.services.reminder_senders import DeliveryResult
from conftest import auth
from test_agency_rent_reminders import _lease


def test_preferences_preview_and_manual_payment_stop(client, monkeypatch):
    monkeypatch.setenv("LANDKEEP_DEMO_MODE", "true")
    monkeypatch.setenv("LANDKEEP_LEASE_REMINDERS", "true")
    landlord = auth(client, "landlord@test.com")
    other = auth(client, "other@test.com")
    response = client.post("/auth/register", json={
        "full_name": "Lease Tenant", "email": "lease-notices@test.com", "phone": "+27825550123",
        "password": "password123",
    })
    assert response.status_code == 201
    tenant_id = response.json()["user"]["id"]
    tenant = {"Authorization": f"Bearer {response.json()['token']}"}
    with SessionLocal() as db:
        lease = _lease(db, db.get(m.Unit, 1), db.get(m.User, tenant_id),
                       start=date(2026, 10, 1), end=date(2027, 10, 1))
        charge = m.RentCharge(lease_id=lease.id, period=date(2026, 11, 1),
                              due_date=date(2026, 11, 5), amount_due=7000)
        db.add(charge)
        db.commit()
        lease_id, charge_id = lease.id, charge.id

    lease_url = f"/lease-notifications/leases/{lease_id}"
    assert client.get(lease_url, headers=tenant).json()["channels"] == [
        {"channel": "email", "enabled": True, "verified": True},
    ]
    assert client.put(lease_url, headers=tenant, json={"channels": ["whatsapp"]}).status_code == 400
    settings_url = "/lease-notifications/settings"
    assert client.put(settings_url, headers=landlord, json={"whatsapp": True}).status_code == 200
    selection = {"channels": ["email", "whatsapp"]}
    assert client.put(lease_url, headers=tenant, json=selection).status_code == 200

    def preview(day):
        response = client.post(f"/reminders/run?preview_date={day}", headers=landlord)
        assert response.status_code == 200
        return response.json()["reminders"]

    assert [row["channel"] for row in preview("2026-11-02")[0]["channels"]] == ["in_app", "email", "whatsapp"]
    assert [row["channel"] for row in preview("2026-11-04")[0]["channels"]] == ["in_app", "email"]
    assert client.put(settings_url, headers=landlord, json={"whatsapp": False}).status_code == 200
    assert len(client.get(lease_url, headers=tenant).json()["channels"]) == 1
    assert client.get("/lease-notifications/inbox", headers=tenant).json()[0]["subject"] == "Reminder channel disabled"

    payment = {"amount": "4500.00", "method": "cash", "request_id": str(uuid4())}
    payment_url = f"/payments/{charge_id}/manual"
    assert client.post(payment_url, headers=other, json=payment).status_code == 404
    assert client.post(payment_url, headers=landlord, json=payment).json()["outstanding"] == 2500
    assert client.post(payment_url, headers=landlord, json=payment).json()["outstanding"] == 2500
    assert "R2,500.00" in preview("2026-11-04")[0]["channels"][0]["message"]
    payment.update(amount="2500.00", request_id=str(uuid4()))
    assert client.post(payment_url, headers=landlord, json=payment).json()["outstanding"] == 0
    assert preview("2026-11-05") == []

    with SessionLocal() as db:
        assert db.scalar(select(m.AgencyRentReminderLog.id)) is None


def test_paid_budget_and_quiet_hours(client, monkeypatch):
    monkeypatch.setenv("LANDKEEP_DEMO_MODE", "false")
    monkeypatch.setenv("SMS_MODE", "real")
    monkeypatch.setenv("WHATSAPP_MODE", "real")
    day = date(2026, 11, 2)
    sent = []

    class Sender:
        def __init__(self, channel):
            self.channel = channel

        def send(self, recipient, subject, message, **kwargs):
            sent.append(self.channel)
            return DeliveryResult()

    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        tenant = m.User(role="tenant", full_name="Budget Tenant", email="budget@test.com",
                        phone="+27825550123", password_hash="unused")
        db.add(tenant)
        db.flush()
        lease = _lease(db, db.get(m.Unit, 1), tenant, start=date(2026, 10, 1), end=date(2027, 10, 1))
        db.add(m.AgencyReminderSettings(agency_id=agency.id, lease_notification_policy={
            "sms": True, "whatsapp": True, "monthly_message_cap": 1,
        }))
        for kind in ("email", "phone"):
            db.add(m.NotificationContactVerification(user_id=tenant.id, kind=kind,
                contact=getattr(tenant, kind), requested_at=m.utcnow(), verified_at=m.utcnow()))
        for channel in ("sms", "whatsapp"):
            save_choice(db, lease, agency.id, channel, True, tenant.id, "tenant")
            db.add(m.ChannelCost(channel=channel, effective_from=date(2020, 1, 1),
                                 cost_per_message=0.25, currency="ZAR"))
        db.commit()

        def run():
            result = agency_reminders.run_reminders(db, agency_id=agency.id, day=day,
                lease_schedule=True, sender_factory=Sender)
            assert result["summary"]["agency_errors"] == []

        monkeypatch.setattr(agency_reminders, "external_delivery_open", lambda: False)
        run()
        assert sent == []
        monkeypatch.setattr(agency_reminders, "external_delivery_open", lambda: True)
        run()
        run()
        assert sent == ["email", "sms"]
        skipped = db.scalar(select(m.AutomationMessage).where(m.AutomationMessage.channel == "whatsapp",
            m.AutomationMessage.status == "skipped"))
        assert skipped.error == "cap reached"
        inbox = db.scalars(select(m.Notification).where(m.Notification.channel == "in_app")).all()
        assert {row.template for row in inbox} == {"rent_reminder", "messaging_cap"}
        assert len([row for row in inbox if row.template == "messaging_cap"]) == 2

    usage = client.get("/lease-notifications/usage", headers=auth(client, "landlord@test.com")).json()
    assert usage["used"] == 1 and usage["percentage"] == 100
    assert float(usage["estimated"]["ZAR"]) == 0.25
