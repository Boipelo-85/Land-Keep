from conftest import auth

APPLICANT = {"full_name": "Naledi Khumalo", "email": "naledi@test.com", "phone": "+27825550123",
             "password": "password123"}


def apply(client, unit_id=1, income=40000, consent=True, id_number="9001015800086"):
    reg = client.post("/auth/register", json=APPLICANT)
    headers = {"Authorization": f"Bearer {reg.json()['token']}"} if reg.status_code == 201 \
        else auth(client, APPLICANT["email"])
    res = client.post("/applications", headers=headers, json={
        "unit_id": unit_id, "monthly_income": income, "employer": "Bank",
        "id_number": id_number, "consent_given": consent})
    return headers, res


def test_full_flow_apply_to_active_tenant(client):
    # 1. applicant applies
    applicant, res = apply(client)
    assert res.status_code == 201, res.text
    body = res.json()
    app_id = body["id"]
    assert body["reference_no"].startswith("LK-") and body["status"] == "submitted"
    assert body["id_number"].endswith("0086") and "9001015" not in body["id_number"]

    landlord = auth(client, "landlord@test.com")
    assert [a["id"] for a in client.get("/applications", headers=landlord).json()] == [app_id]

    # 2. landlord runs the credit check
    checked = client.post(f"/applications/{app_id}/credit-check", headers=landlord).json()
    assert checked["status"] == "under_review"
    assert 300 <= checked["credit_score"] <= 850
    assert checked["recommendation"] in ("approve", "review", "decline")

    # 3. landlord approves -> applicant is notified by email and SMS
    approved = client.post(f"/applications/{app_id}/decision", headers=landlord,
                           json={"decision": "approved", "note": "Welcome"}).json()
    assert approved["status"] == "approved"

    # 4. convert to tenant, lease PDF is created
    lease = client.post(f"/applications/{app_id}/convert", headers=landlord,
                        json={"start_date": "2026-11-01", "term_months": 12, "due_day": 1})
    assert lease.status_code == 201, lease.text
    lease = lease.json()
    assert lease["status"] == "pending" and lease["end_date"] == "2027-10-31"
    pdf = client.get(lease["pdf_url"], headers=applicant)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # unit is no longer offered while the lease is pending
    assert 1 not in [u["id"] for u in client.get("/units/vacant").json()]
    assert 2 in [u["id"] for u in client.get("/units/vacant").json()]

    # 5. tenant accepts the lease
    accepted = client.post(f"/leases/{lease['id']}/accept", headers=applicant).json()
    assert accepted["status"] == "active" and accepted["accepted_at"]

    # tracking timeline shows the whole journey
    timeline = client.get(f"/applications/{app_id}", headers=applicant).json()["timeline"]
    assert [t["status"] for t in timeline] == \
        ["submitted", "under_review", "approved", "lease_issued", "active_tenant"]

    # notifications were recorded for every step
    from app import models as m
    from app.database import SessionLocal
    with SessionLocal() as s:
        templates = [n.template for n in s.query(m.Notification).order_by(m.Notification.id)]
    assert "application_received" in templates and "application_approved" in templates
    assert "lease_ready" in templates and "lease_accepted_landlord" in templates
    assert templates.count("application_approved") == 2  # email + SMS


def test_consent_is_required(client):
    _, res = apply(client, consent=False)
    assert res.status_code == 400
    assert "consent" in res.json()["detail"].lower()


def test_invalid_id_number_rejected(client):
    _, res = apply(client, id_number="123")
    assert res.status_code == 422


def test_cannot_decide_before_credit_check(client):
    _, res = apply(client)
    landlord = auth(client, "landlord@test.com")
    res = client.post(f"/applications/{res.json()['id']}/decision", headers=landlord,
                      json={"decision": "approved"})
    assert res.status_code == 409


def test_cannot_convert_unless_approved(client):
    _, res = apply(client)
    landlord = auth(client, "landlord@test.com")
    res = client.post(f"/applications/{res.json()['id']}/convert", headers=landlord,
                      json={"start_date": "2026-11-01"})
    assert res.status_code == 409


def test_permissions(client):
    applicant, res = apply(client)
    app_id = res.json()["id"]

    # applicants cannot use landlord actions
    assert client.post(f"/applications/{app_id}/credit-check", headers=applicant).status_code == 403
    # not logged in
    assert client.get("/applications").status_code == 401
    # another landlord cannot see this landlord's application
    other = auth(client, "other@test.com")
    assert client.get(f"/applications/{app_id}", headers=other).status_code == 404
    assert client.post(f"/applications/{app_id}/credit-check", headers=other).status_code == 404
    assert client.get("/applications", headers=other).json() == []
    # another applicant cannot see it either
    client.post("/auth/register", json={**APPLICANT, "email": "someone@test.com"})
    stranger = auth(client, "someone@test.com")
    assert client.get(f"/applications/{app_id}", headers=stranger).status_code == 404


def test_duplicate_application_blocked(client):
    apply(client)
    _, res = apply(client)
    assert res.status_code == 409


def test_register_always_creates_tenant(client):
    res = client.post("/auth/register", json={**APPLICANT, "role": "landlord"})
    assert res.json()["user"]["role"] == "tenant"
    assert client.post("/auth/login", json={"email": APPLICANT["email"], "password": "wrong"}).status_code == 401
