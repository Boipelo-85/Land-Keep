import hashlib
import hmac
import json
from datetime import timedelta

from sqlalchemy import select

from app import models as m
from app.database import SessionLocal
from app.security import create_token, hash_password
from app.services import automation_channels as channels
from app.services.automation import run_followups
from conftest import auth


def test_removed_demo_endpoints_and_fixture_account(client):
    headers = auth(client, "landlord@test.com")
    assert client.post("/automation/demo/run", headers=headers).status_code == 404
    assert client.post("/automation/demo/reset", headers=headers).status_code == 404
    assert client.get("/automation/demo/phone/1", headers=headers).status_code == 404
    with SessionLocal() as db:
        fixture = m.User(email="automation-demo@landkeep.test", role="landlord",
                         full_name="Old fixture", password_hash=hash_password("password123"))
        db.add(fixture)
        db.commit()
        token = create_token(fixture.id)
    assert client.post("/auth/login", json={"email": fixture.email, "password": "password123"}).status_code == 401
    assert client.get("/automation/log", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_live_meta_send(monkeypatch):
    monkeypatch.setenv("WHATSAPP_MODE", "real")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WHATSAPP_TOKEN", "mock-live-token")
    monkeypatch.setenv("WHATSAPP_GRAPH_VERSION", "v24.0")

    def send(url, **kwargs):
        assert url == "https://graph.facebook.com/v24.0/123/messages"
        assert kwargs["json"]["to"] == "27821234567"
        assert kwargs["json"]["template"]["name"] == "landkeep_rent_reminder"
        return channels.httpx.Response(200, request=channels.httpx.Request("POST", url),
                                       json={"messages": [{"id": "wamid.live"}]})

    monkeypatch.setattr(channels.httpx, "post", send)
    adapter = channels.MetaWhatsAppChannel("landkeep_rent_reminder")
    assert adapter.send("+27821234567", "Rent", "Rent due").provider_message_id == "wamid.live"


def test_live_webhook_updates_only_configured_sender_and_records_reply_once(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "webhook-test-secret")
    with SessionLocal() as db:
        agency = db.scalar(select(m.User).where(m.User.email == "landlord@test.com"))
        tenant = m.User(role="tenant", full_name="Tenant", email="resident@example.test",
                        phone="+27821234567", password_hash="unused", whatsapp_opt_in=True)
        db.add(tenant)
        db.flush()
        db.add(m.AutomationMessage(agency_id=agency.id, tenant_id=tenant.id, kind="rent_reminder",
            direction="outbound", mode="real", channel="whatsapp", status="sent", subject="Rent",
            body="Rent", provider_message_id="wamid.sent"))
        db.commit()

    headers = auth(client, "landlord@test.com")
    url = "/automation/whatsapp/webhook"

    def post(phone_id, signed=True):
        event = {"metadata": {"phone_number_id": phone_id},
                 "statuses": [{"id": "wamid.sent", "status": "read"}],
                 "messages": [{"id": "wamid.reply", "from": "27821234567", "text": {"body": "STOP"}}]}
        body = json.dumps({"entry": [{"changes": [{"field": "messages", "value": event}]}]}).encode()
        signature = hmac.new(b"webhook-test-secret", body, hashlib.sha256).hexdigest()
        return client.post(url, content=body, headers={"X-Hub-Signature-256": "sha256=" + signature} if signed else {})

    assert post("123", signed=False).status_code == 403
    assert post("999").status_code == 200
    assert len(client.get("/automation/log", headers=headers).json()["messages"]) == 1
    for _ in range(2):
        assert post("123").status_code == 200
    messages = client.get("/automation/log", headers=headers).json()["messages"]
    assert len(messages) == 2
    assert all(row["status"] == "read" for row in messages)
    with SessionLocal() as db:
        assert not db.get(m.User, tenant.id).whatsapp_opt_in


def test_repair_followups_use_consent_and_dedupe(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_MODE", "real")
    calls = []

    def send(self, recipient, subject, message, **kwargs):
        calls.append((recipient, message))
        return channels.DeliveryResult("wamid.followup")

    monkeypatch.setattr(channels.MetaWhatsAppChannel, "send", send)
    now = m.utcnow()
    with SessionLocal() as db:
        unit = db.scalar(select(m.Unit).where(m.Unit.unit_number == "A01"))
        for index, consent in enumerate((True, False)):
            tenant = m.User(role="tenant", full_name="Tenant", email=f"repair-{index}@example.test",
                            phone=f"+2782123456{index}", password_hash="unused", whatsapp_opt_in=consent)
            db.add(tenant)
            db.flush()
            db.add(m.MaintenanceRequest(unit_id=unit.id, tenant_id=tenant.id, description="Repair",
                                        status="resolved", resolved_at=now - timedelta(hours=49)))
        db.commit()
        assert run_followups(db, now) == 1
        assert run_followups(db, now) == 0
    assert len(calls) == 1
    assert "Reply 1 for yes, 2 for no" in calls[0][1]
