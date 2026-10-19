import os
import sys
import tempfile
from pathlib import Path

# Use a throwaway database so tests never touch landkeep.db. Must be set before app imports.
_tmp = tempfile.mkdtemp()
os.environ["LANDKEEP_DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models as m  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        landlord = m.User(role="landlord", full_name="Thabo Mokoena", email="landlord@test.com",
                          phone="+27715550100", password_hash=hash_password("password123"))
        other = m.User(role="landlord", full_name="Other Landlord", email="other@test.com",
                       phone="+27715550101", password_hash=hash_password("password123"))
        s.add_all([landlord, other])
        s.flush()
        prop = m.Property(landlord_id=landlord.id, name="Baobab Court", address="12 Church Street", city="Pretoria")
        s.add(prop)
        s.flush()
        s.add_all([m.Unit(property_id=prop.id, unit_number="A01", bedrooms=2, monthly_rent=7000, status="vacant"),
                   m.Unit(property_id=prop.id, unit_number="A02", bedrooms=1, monthly_rent=5000, status="vacant")])
        s.commit()
    with TestClient(app) as c:
        yield c


def auth(client, email, password="password123"):
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}
