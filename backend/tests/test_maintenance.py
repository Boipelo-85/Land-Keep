"""Tenant can report a maintenance problem (with optional photo)."""
from datetime import date, timedelta
from io import BytesIO

from conftest import auth

from app import models as m
from app.database import SessionLocal
from app.security import hash_password

TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c"
    b"\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c"
    b"\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08"
    b"\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14"
    b"\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xaa\xff\xd9"
)


def _make_tenant_with_lease(email="tenant@test.com", unit_id=1):
    with SessionLocal() as s:
        tenant = m.User(role="tenant", full_name="Sipho Dlamini", email=email,
                        phone="+27825550999", password_hash=hash_password("password123"))
        s.add(tenant)
        s.flush()
        unit = s.get(m.Unit, unit_id)
        unit.status = "occupied"
        start = date.today().replace(day=1) - timedelta(days=60)
        lease = m.Lease(unit_id=unit.id, tenant_id=tenant.id, start_date=start,
                        end_date=start + timedelta(days=365), monthly_rent=unit.monthly_rent,
                        deposit=unit.monthly_rent, due_day=1, status="active",
                        accepted_at=m.utcnow())
        s.add(lease)
        s.commit()
        return tenant.id


def test_report_without_photo(client):
    _make_tenant_with_lease()
    headers = auth(client, "tenant@test.com")
    res = client.post("/maintenance", headers=headers,
                      data={"description": "The kitchen tap is dripping constantly."})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "open"
    assert body["has_photo"] is False
    assert body["description"].startswith("The kitchen tap")

    mine = client.get("/maintenance/mine", headers=headers).json()
    assert len(mine) == 1 and mine[0]["id"] == body["id"]

    with SessionLocal() as s:
        templates = [n.template for n in s.query(m.Notification).all()]
    assert templates.count("maintenance_received") == 2  # email + SMS


def test_report_with_photo(client):
    _make_tenant_with_lease()
    headers = auth(client, "tenant@test.com")
    res = client.post(
        "/maintenance",
        headers=headers,
        data={"description": "Water leaking under the bathroom basin."},
        files={"photo": ("leak.jpg", BytesIO(TINY_JPEG), "image/jpeg")},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["has_photo"] is True

    photo = client.get(f"/maintenance/{body['id']}/photo", headers=headers)
    assert photo.status_code == 200
    assert photo.content.startswith(b"\xff\xd8")


def test_wrong_photo_type(client):
    _make_tenant_with_lease()
    headers = auth(client, "tenant@test.com")
    res = client.post(
        "/maintenance",
        headers=headers,
        data={"description": "Please look at this document."},
        files={"photo": ("notes.pdf", BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert res.status_code == 400
    assert "jpg" in res.json()["detail"].lower() or "webp" in res.json()["detail"].lower()


def test_photo_over_5mb(client):
    _make_tenant_with_lease()
    headers = auth(client, "tenant@test.com")
    big = b"\xff\xd8" + (b"x" * (5 * 1024 * 1024)) + b"\xff\xd9"
    res = client.post(
        "/maintenance",
        headers=headers,
        data={"description": "Huge photo of the cracked wall."},
        files={"photo": ("huge.jpg", BytesIO(big), "image/jpeg")},
    )
    assert res.status_code == 400
    assert "5" in res.json()["detail"]


def test_no_active_lease(client):
    client.post("/auth/register", json={
        "full_name": "No Lease", "email": "nolease@test.com",
        "phone": "+27821110000", "password": "password123",
    })
    headers = auth(client, "nolease@test.com")
    res = client.post("/maintenance", headers=headers,
                      data={"description": "Something is broken in the unit."})
    assert res.status_code == 400
    assert "active lease" in res.json()["detail"].lower()


def test_landlord_forbidden(client):
    landlord = auth(client, "landlord@test.com")
    assert client.post("/maintenance", headers=landlord,
                       data={"description": "I am the landlord trying this."}).status_code == 403
    assert client.get("/maintenance/mine", headers=landlord).status_code == 403


def test_other_tenant_cannot_see_photo(client):
    _make_tenant_with_lease("owner@test.com", unit_id=1)
    _make_tenant_with_lease("neighbour@test.com", unit_id=2)
    owner = auth(client, "owner@test.com")
    other = auth(client, "neighbour@test.com")

    created = client.post(
        "/maintenance",
        headers=owner,
        data={"description": "Sparks from the lounge plug socket."},
        files={"photo": ("sparks.jpg", BytesIO(TINY_JPEG), "image/jpeg")},
    ).json()

    assert client.get(f"/maintenance/{created['id']}/photo", headers=other).status_code == 404
    assert client.get(f"/maintenance/{created['id']}/photo", headers=owner).status_code == 200
