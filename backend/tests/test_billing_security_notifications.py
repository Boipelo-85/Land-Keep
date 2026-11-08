from datetime import date
from types import SimpleNamespace
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app import models as m
from app.database import SessionLocal
from app.services.leases import add_months, generate_charges, generate_recurring_charges
from app.services import notifications
from app.routers import maintenance


def test_month_arithmetic():
    assert add_months(date(2026, 11, 15), 12) == date(2027, 11, 15)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_recurring_rent_catches_up_without_duplicates(client):
    with SessionLocal() as db:
        lease = m.Lease(unit_id=1, tenant_id=1, start_date=date(2026, 1, 15),
                        end_date=date(2026, 3, 14), monthly_rent=7000,
                        deposit=7000, due_day=1, status='active')
        db.add(lease)
        db.commit()
        assert generate_charges(db, lease, date(2026, 1, 15)) == 1
        assert generate_charges(db, lease, date(2026, 1, 15)) == 0
        db.commit()
        assert generate_recurring_charges(db, date(2026, 2, 1)) == 1
        assert generate_recurring_charges(db, date(2026, 2, 1)) == 0
        assert generate_recurring_charges(db, date(2026, 5, 1)) == 1
        charges = db.scalars(select(m.RentCharge).order_by(m.RentCharge.period)).all()
        assert [row.period for row in charges] == [date(2026, i, 1) for i in (1, 2, 3)]
        assert charges[0].due_date == date(2026, 1, 15)
        db.add(m.RentCharge(lease_id=lease.id, period=date(2026, 1, 1), amount_due=7000, due_date=date(2026, 1, 15)))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_notifications_report_demo_success_and_failure(monkeypatch):
    user = SimpleNamespace(id=1, email='user@example.test', phone='+27820000000')
    monkeypatch.setenv('LANDKEEP_PROVIDER_MIN_INTERVAL_SECONDS', '0')
    assert notifications._deliver('email', user, 'Subject', 'Body') == 'simulated'
    monkeypatch.setattr(notifications, 'build_sender', lambda channel: object())
    monkeypatch.setattr(notifications, 'send_with_retries', lambda *a, **kw: None)
    assert notifications._deliver('email', user, 'Subject', 'Body') == 'sent'
    def fail(*args, **kwargs):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(notifications, 'send_with_retries', fail)
    assert notifications._deliver('email', user, 'Subject', 'Body') == 'failed'


def test_maintenance_falls_back_after_failure(monkeypatch):
    settings = SimpleNamespace(enabled_channels=['email', 'sms', 'whatsapp'], channel_strategy='fallback', contact_email=None, contact_phone=None)
    agency = SimpleNamespace(email='agency@example.test', phone='+27820000000')
    db = SimpleNamespace(scalar=lambda query: settings, get=lambda *args: agency)
    channels = []
    monkeypatch.setattr(maintenance, 'build_sender', lambda channel: channel)
    def send(channel, *args):
        channels.append(channel)
        if channel == 'email':
            raise RuntimeError('email failed')
    monkeypatch.setattr(maintenance, 'send_with_retries', send)
    maintenance._notify_landlord(db, SimpleNamespace(agency_id=1), 'Urgent', 'Body', True)
    assert channels == ['email', 'sms']


@pytest.mark.parametrize("secret", ["", "short", "dev-secret-change-me"])
def test_security_rejects_weak_secret(secret):
    env = {**os.environ, 'LANDKEEP_SECRET': secret}
    result = subprocess.run([sys.executable, '-c', 'import app.security'], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Set LANDKEEP_SECRET' in result.stderr

