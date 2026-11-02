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
<<<<<<< HEAD
    tap_help = maintenance_chat.fallback_analysis(user_text="My tap can't take out water")
    assert tap_help.category == "plumbing"
    assert tap_help.diy_appropriate is True
    assert "Check whether other taps have water" in tap_help.reply
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5


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
<<<<<<< HEAD
    assert requests.json()[0]["primary_issue"] == "I smell gas in the kitchen"
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5


def test_other_agency_cannot_read_chat(client):
    _, lease_id = _tenant_with_lease()
    tenant_headers = auth(client, "tenant-chat@test.com")
    started = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=tenant_headers)
    conversation_id = started.json()["id"]
    other_landlord = auth(client, "other@test.com")
    response = client.get(f"/maintenance/conversations/{conversation_id}", headers=other_landlord)
    assert response.status_code == 404
<<<<<<< HEAD


def test_ai_outage_keeps_chat_open_and_allows_more_messages(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    monkeypatch.setattr(maintenance_chat, "analyze_with_claude", lambda *args: (_ for _ in ()).throw(RuntimeError("AI unavailable")))
    tenant_headers = auth(client, "tenant-chat@test.com")
    started = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=tenant_headers)
    conversation_id = started.json()["id"]

    first = client.post(f"/maintenance/conversations/{conversation_id}/messages",
                        data={"text": "The tap is not giving water"}, headers=tenant_headers)
    assert first.status_code == 200
    assert first.json()["status"] == "open"
    assert first.json()["request_id"] is None
    assert "other taps" in first.json()["messages"][-1]["text"]

    second = client.post(f"/maintenance/conversations/{conversation_id}/messages",
                         data={"text": "It started this morning"}, headers=tenant_headers)
    assert second.status_code == 200
    assert second.json()["status"] == "open"
    assert len([msg for msg in second.json()["messages"] if msg["role"] == "tenant"]) == 2


def test_tenant_can_resume_escalated_chat_and_add_followup(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    tenant_headers = auth(client, "tenant-chat@test.com")
    started = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=tenant_headers)
    conversation_id = started.json()["id"]
    escalated = client.post(f"/maintenance/conversations/{conversation_id}/escalate", headers=tenant_headers)
    assert escalated.status_code == 200

    def fake_analysis(text, paths, *, escalated=False):
        assert escalated is True
        return maintenance_chat.Analysis(reply="Contact someone you trust who may have a spare key; don't force the door. These suggestions are general guidance, not a professional inspection.",
            category="doors_locks", urgency="medium", summary="Tenant lost keys", likely_cause="Unknown",
            confidence=0.9, diy_appropriate=True)
    monkeypatch.setattr(maintenance_chat, "analyze_with_claude", fake_analysis)

    resumed = client.get("/maintenance/conversations/mine", headers=tenant_headers)
    assert resumed.status_code == 200
    assert resumed.json()[0]["id"] == conversation_id

    followup = client.post(f"/maintenance/conversations/{conversation_id}/messages",
                           data={"text": "Lost all my keys"}, headers=tenant_headers)
    assert followup.status_code == 200
    assert followup.json()["status"] == "escalated"
    assert followup.json()["messages"][-1]["role"] == "bot"
    assert "spare key" in followup.json()["messages"][-1]["text"]
    assert "don't force" in followup.json()["messages"][-1]["text"]


def test_photo_consent_can_be_given_inside_an_existing_chat(client):
    _, lease_id = _tenant_with_lease()
    tenant_headers = auth(client, "tenant-chat@test.com")
    started = client.post("/maintenance/conversations", json={"lease_id": lease_id, "photo_sharing_consent": False}, headers=tenant_headers)
    conversation_id = started.json()["id"]
    assert started.json()["photo_sharing_consent"] is False

    accepted = client.post(f"/maintenance/conversations/{conversation_id}/photo-consent",
                           json={"consent": True}, headers=tenant_headers)
    assert accepted.status_code == 200
    assert accepted.json()["photo_sharing_consent"] is True


def test_followup_does_not_close_unresolved_report(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, "tenant-chat@test.com")
    monkeypatch.setattr(maintenance_chat, "analyze_with_claude", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    cid = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=headers).json()["id"]
    client.post(f"/maintenance/conversations/{cid}/escalate", headers=headers)
    response = client.post(f"/maintenance/conversations/{cid}/messages", data={"text": "It is not fixed, still leaking"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "escalated"
    assert "chat is now closed" not in response.json()["messages"][-1]["text"]


def test_urgent_ai_assessment_creates_report(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, "tenant-chat@test.com")
    monkeypatch.setattr(maintenance_chat, "analyze_with_claude", lambda *a, **k: maintenance_chat.Analysis(
        reply="Please keep away and ask your landlord for help.", category="plumbing", urgency="high",
        summary="Major leak", likely_cause="Pipe damage", confidence=0.9, diy_appropriate=False))
    cid = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=headers).json()["id"]
    response = client.post(f"/maintenance/conversations/{cid}/messages", data={"text": "Water coming through the ceiling"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "escalated"
    assert response.json()["request_id"]


def test_resolution_updates_report_and_closed_chat_rejects_escalation(client):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, "tenant-chat@test.com")
    cid = client.post("/maintenance/conversations", json={"lease_id": lease_id}, headers=headers).json()["id"]
    client.post(f"/maintenance/conversations/{cid}/escalate", headers=headers)
    response = client.post(f"/maintenance/conversations/{cid}/resolve", json={"solved": True}, headers=headers)
    assert response.status_code == 200
    with SessionLocal() as db:
        req = db.query(m.MaintenanceRequest).filter_by(conversation_id=cid).one()
        assert req.status == "resolved"
    assert client.post(f"/maintenance/conversations/{cid}/escalate", headers=headers).status_code == 409


def test_fallback_uses_tenant_context_only():
    result = maintenance_chat.fallback_analysis(user_text="bot: Check your geyser and hot water.\ntenant: The kitchen tap is leaking")
    assert result.category == "plumbing"
    assert "leak" in result.reply


def test_short_messages_and_context_after_escalation(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, 'tenant-chat@test.com')
    monkeypatch.setattr(maintenance_chat, 'analyze_with_claude', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
    cid = client.post('/maintenance/conversations', json={'lease_id': lease_id}, headers=headers).json()['id']
    client.post(f'/maintenance/conversations/{cid}/escalate', headers=headers)
    def send(text):
        response = client.post(f'/maintenance/conversations/{cid}/messages', data={'text': text}, headers=headers)
        assert response.status_code == 200
        assert response.json()['status'] == 'escalated'
        assert response.json()['assistant_mode'] == 'local'
        return response.json()['messages'][-1]['text']
    assert 'What did you lose' in send('I lost')
    assert 'locked out' in send('My keys')
    assert "can't get inside" in send("I'm outside")
    assert 'Hi!' in send('hey')
    assert 'still open' in send('not fixed')
    with SessionLocal() as db:
        assert db.query(m.MaintenanceRequest).filter_by(conversation_id=cid).count() == 1


def test_local_plumbing_followup_advances_conversation():
    result = maintenance_chat.conversational_fallback('tenant: My tap has no water\nbot: Check other taps\ntenant: Other taps work')
    assert 'visible leak' in result.reply
    assert 'Check whether other taps' not in result.reply


def test_manual_escalation_immediately_returns_relevant_guidance(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, 'tenant-chat@test.com')
    monkeypatch.setattr(maintenance_chat, 'analyze_with_claude', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
    cid = client.post('/maintenance/conversations', json={'lease_id': lease_id}, headers=headers).json()['id']
    client.post(f'/maintenance/conversations/{cid}/messages', data={'text': 'My kitchen tap is leaking'}, headers=headers)
    response = client.post(f'/maintenance/conversations/{cid}/escalate', headers=headers)
    assert response.status_code == 200
    guide = response.json()['messages'][-1]['text']
    assert 'While you wait:' in guide
    assert 'catch drips' in guide
    assert 'keep chatting' in guide
    assert response.json()['status'] == 'escalated'
    with SessionLocal() as db:
        req = db.query(m.MaintenanceRequest).filter_by(conversation_id=cid).one()
        assert req.ai_category == 'plumbing'
        assert req.ai_urgency == 'medium'
    again = client.post(f'/maintenance/conversations/{cid}/escalate', headers=headers)
    assert again.json()['request_id'] == response.json()['request_id']


def test_not_solved_escalation_includes_interim_guidance(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, 'tenant-chat@test.com')
    monkeypatch.setattr(maintenance_chat, 'analyze_with_claude', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
    cid = client.post('/maintenance/conversations', json={'lease_id': lease_id}, headers=headers).json()['id']
    client.post(f'/maintenance/conversations/{cid}/messages', data={'text': 'My socket does not work'}, headers=headers)
    response = client.post(f'/maintenance/conversations/{cid}/resolve', json={'solved': False}, headers=headers)
    guide = response.json()['messages'][-1]['text']
    assert 'qualified electrician' in guide
    assert "don't open panels" in guide
    assert response.json()['status'] == 'escalated'


def test_interim_guidance_covers_categories_and_emergency():
    cases = [('The sink is blocked', 'plumbing', 'Stop using'),
             ('My keys are lost', 'doors_locks', 'authorised access'),
             ('The wall needs painting', 'other', 'Keep the affected area clear'),
             ('I smell gas', 'other', 'Leave the area')]
    for issue, category, guidance in cases:
        result = maintenance_chat.interim_assessment(issue)
        assert result.category == category
        assert guidance in result.reply
    assert maintenance_chat.interim_assessment('I smell gas').urgency == 'emergency'


def test_exact_missing_keys_messages_from_screenshot(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    headers = auth(client, 'tenant-chat@test.com')
    monkeypatch.setattr(maintenance_chat,'analyze_with_claude',lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline')))
    cid=client.post('/maintenance/conversations',json={'lease_id':lease_id},headers=headers).json()['id']
    client.post(f'/maintenance/conversations/{cid}/escalate',headers=headers)
    first=client.post(f'/maintenance/conversations/{cid}/messages',data={'text':'I cant find mu unit keys hey.'},headers=headers).json()
    assert 'locked out' in first['messages'][-1]['text']
    assert first['priority']=='high'
    second=client.post(f'/maintenance/conversations/{cid}/messages',data={'text':'The keys'},headers=headers).json()
    assert 'authorised access' in second['messages'][-1]['text']
    third=client.post(f'/maintenance/conversations/{cid}/messages',data={'text':'Im outside hey'},headers=headers).json()
    assert "can't get inside" in third['messages'][-1]['text']
    assert third['status']=='escalated'


def test_local_chat_uses_learned_category_for_unfamiliar_wording(monkeypatch):
    from app.services import maintenance_classifier
    monkeypatch.setattr(maintenance_classifier,'predict',lambda text:{'category':'plumbing','score':.8,'needs_review':False,'suggested_priority':'low'})
    response=maintenance_chat.conversational_fallback('tenant: The basin empties strangely')
    assert response.category=='plumbing'
    assert 'blockage' in response.reply


def test_negative_plumbing_followup_is_not_reversed():
    response=maintenance_chat.conversational_fallback('tenant: My kitchen tap has no water\ntenant: No other taps work')
    assert 'also have no water' in response.reply
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
