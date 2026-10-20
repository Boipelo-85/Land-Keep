from datetime import date

from app import models as m
from app.database import SessionLocal
from app.services import maintenance_chat
from app.security import hash_password
from conftest import auth


def _tenant_with_lease():
    with SessionLocal() as db:
        landlord = db.query(m.User).filter_by(email="landlord@test.com").one()
        unit = db.query(m.Unit).filter_by(unit_number="A01").one()
        tenant = m.User(role="tenant", full_name="Nandi Dlamini", email="tenant-chat@test.com",
                        phone="+27821234567", password_hash=hash_password("password123"))
        db.add(tenant); db.flush()
        lease = m.Lease(unit_id=unit.id, tenant_id=tenant.id, start_date=date(2025, 1, 1),
                        end_date=date(2027, 1, 1), monthly_rent=7000, deposit=7000,
                        due_day=1, status="active")
        db.add(lease); db.commit()
        return tenant.id, lease.id


def test_emergency_triggers_and_fallback_are_safe():
    assert maintenance_chat.detect_emergency("There are sparks from exposed wiring") == "electrical"
    assert maintenance_chat.detect_emergency("water is dripping under the sink") is None
    result = maintenance_chat.validate_analysis({"bad": "shape"})
    assert result.category == "other"
    assert result.urgency == "medium"
    assert result.diy_appropriate is False


def test_emergency_chat_skips_ai_and_creates_urgent_agency_request(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    monkeypatch.setenv("LANDKEEP_REMINDER_CONSOLE", "true")
    monkeypatch.setattr(maintenance_chat, "analyze_with_claude", lambda *args: (_ for _ in ()).throw(AssertionError("AI must not run for emergency")))
    tenant_headers = auth(client, "tenant-chat@test.com")
    started = client.post("/maintenance/conversations", json={"lease_id": lease_id, "photo_sharing_consent": True}, headers=tenant_headers)
    assert started.status_code == 201
    conversation_id = started.json()["id"]
    response = client.post(f"/maintenance/conversations/{conversation_id}/messages",
                           data={"text": "I smell gas in the kitchen"}, headers=tenant_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "escalated"
    assert "leave the area" in response.json()["messages"][-2]["text"].lower()
    landlord = auth(client, "landlord@test.com")
    requests = client.get("/maintenance/requests?urgency=emergency", headers=landlord)
    assert requests.status_code == 200
    assert len(requests.json()) == 1
    assert requests.json()[0]["tenant"] == "Nandi Dlamini"


def test_other_agency_cannot_read_chat(client):
    _, lease_id = _tenant_with_lease()
    tenant_headers = auth(client, "tenant-chat@test.com")
    started = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=tenant_headers)
    conversation_id = started.json()["id"]
    other_landlord = auth(client, "other@test.com")
    response = client.get(f"/maintenance/conversations/{conversation_id}", headers=other_landlord)
    assert response.status_code == 404
