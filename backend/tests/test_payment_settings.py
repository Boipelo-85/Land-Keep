import pytest
from pydantic import ValidationError
from datetime import date
from types import SimpleNamespace

from app import models as m
from app.database import SessionLocal
from app.routers.payments import PayFastSettingsIn
from app.routers import payments as payment_routes
from app.security import hash_password
from conftest import auth


@pytest.mark.parametrize("bad_value", [
    "1234567", "123456789", "46f0cd694581a", "my-secret-passphrase", "１２３４５６７８",
])
def test_merchant_id_validation_rejects_wrong_shape_and_secrets(bad_value):
    with pytest.raises(ValidationError, match="8-digit PayFast merchant ID"):
        PayFastSettingsIn(payfast_merchant_id=bad_value, current_password="password123")


def test_eight_digit_merchant_id_format_is_accepted_for_both_modes():
    # PayFast documents the same 8-character numeric format for its credentials;
    # sandbox and live IDs are distinct account values, not different formats.
    assert PayFastSettingsIn(payfast_merchant_id="10000100", current_password="password123").payfast_merchant_id == "10000100"


def test_tenant_payments_cannot_be_enabled_until_verified(client, monkeypatch):
    monkeypatch.setattr(payment_routes, "_notify_merchant_change", lambda *args: None)
    headers = auth(client, "landlord@test.com")
    body = {"payfast_merchant_id": "12345678", "current_password": "password123",
            "payments_enabled": True}

    rejected = client.put("/payments/settings", headers=headers, json=body)
    assert rejected.status_code == 409
    assert "Verify your PayFast account" in rejected.json()["detail"]

    body["payments_enabled"] = False
    saved = client.put("/payments/settings", headers=headers, json=body)
    assert saved.status_code == 200
    assert saved.json()["verification_status"] == "not_verified"
    assert saved.json()["payments_enabled"] is False

    with SessionLocal() as db:
        settings = db.query(m.AgencyPaymentSettings).one()
        settings.verification_status = "verified"
        settings.verified_at = m.utcnow()
        db.commit()

    body["payfast_merchant_id"] = None
    body["payments_enabled"] = True
    enabled = client.put("/payments/settings", headers=headers, json=body)
    assert enabled.status_code == 200
    assert enabled.json()["verification_status"] == "verified"
    assert enabled.json()["payments_enabled"] is True


def test_merchant_id_change_resets_verification_and_audits_only_masked_values(client, monkeypatch):
    monkeypatch.setattr(payment_routes, "_notify_merchant_change", lambda *args: None)
    headers = auth(client, "landlord@test.com")
    original = client.put("/payments/settings", headers=headers, json={
        "payfast_merchant_id": "12345678", "current_password": "password123",
        "payments_enabled": False,
    })
    assert original.status_code == 200
    with SessionLocal() as db:
        settings = db.query(m.AgencyPaymentSettings).one()
        settings.verification_status = "verified"
        settings.payments_enabled = True
        db.commit()

    changed = client.put("/payments/settings", headers=headers, json={
        "payfast_merchant_id": "87654321", "current_password": "password123",
    })
    assert changed.status_code == 200
    assert changed.json()["payfast_merchant_id_masked"] == "8765****"
    assert changed.json()["verification_status"] == "not_verified"
    assert changed.json()["payments_enabled"] is False
    with SessionLocal() as db:
        audits = db.query(m.AgencyPaymentSettingsAudit).order_by(m.AgencyPaymentSettingsAudit.id).all()
        assert len(audits) == 2
        assert audits[-1].old_merchant_id_masked == "1234****"
        assert audits[-1].new_merchant_id_masked == "8765****"


def test_save_merchant_id_and_check_screen_state_after_saving(client, monkeypatch):
    """Test that saving a merchant ID updates the screen state correctly."""
    monkeypatch.setattr(payment_routes, "_notify_merchant_change", lambda *args: None)
    headers = auth(client, "landlord@test.com")
    
    # Save a merchant ID
    response = client.put("/payments/settings", headers=headers, json={
        "payfast_merchant_id": "10005678",
        "current_password": "password123",
        "payments_enabled": False,
    })
    assert response.status_code == 200
    
    # Check the response contains the expected screen state
    data = response.json()
    assert data["payfast_merchant_id_masked"] == "1000****"
    assert data["verification_status"] == "not_verified"
    assert data["payments_enabled"] is False
    assert data["verified_at"] is None
    
    # Verify the data was actually saved in the database
    with SessionLocal() as db:
        settings = db.query(m.AgencyPaymentSettings).one()
        assert settings.payfast_merchant_id == "10005678"
        assert settings.verification_status == "not_verified"
        assert settings.payments_enabled is False


def test_settings_change_requires_correct_password(client, monkeypatch):
    monkeypatch.setattr(payment_routes, "_notify_merchant_change", lambda *args: None)
    headers = auth(client, "landlord@test.com")
    response = client.put("/payments/settings", headers=headers, json={
        "payfast_merchant_id": "12345678", "current_password": "wrong-password",
    })
    assert response.status_code == 401


@pytest.mark.parametrize("verification_status,enabled", [("not_verified", False), ("verified", False)])
def test_tenant_checkout_remains_blocked_until_account_is_verified_and_enabled(
    client, monkeypatch, verification_status, enabled,
):
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "10000100")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", "sandbox-key")
    monkeypatch.setenv("PAYFAST_SPLIT_PAYMENTS_ENABLED", "true")
    with SessionLocal() as db:
        landlord = db.query(m.User).filter_by(email="landlord@test.com").one()
        unit = db.query(m.Unit).filter_by(unit_number="A01").one()
        tenant = m.User(role="tenant", full_name="Tenant Test", email="tenant@test.com",
                        phone=None, password_hash=hash_password("password123"))
        db.add(tenant)
        db.flush()
        lease = m.Lease(unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1),
                        end_date=date(2027, 1, 1), monthly_rent=1000, deposit=1000,
                        due_day=1, status="active")
        db.add(lease)
        db.flush()
        charge = m.RentCharge(lease_id=lease.id, period=date(2026, 10, 1), amount_due=1000,
                              due_date=date(2026, 10, 1))
        settings = m.AgencyPaymentSettings(agency_id=landlord.id,
                                           payfast_merchant_id="12345678",
                                           verification_status=verification_status,
                                           payments_enabled=enabled)
        db.add_all([charge, settings])
        db.commit()
        tenant_email = tenant.email

    response = client.post(f"/payments/{charge.id}/checkout",
                           headers=auth(client, tenant_email))
    assert response.status_code == 409
    assert "verifies and enables" in response.json()["detail"]


def test_confirmed_test_payment_marks_only_its_agency_verified(client, monkeypatch):
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "10000100")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", "sandbox-key")
    monkeypatch.setenv("PAYFAST_PASSPHRASE", "")
    monkeypatch.setenv("PAYFAST_SPLIT_PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("PAYFAST_MODE", "sandbox")
    monkeypatch.setattr(payment_routes, "is_valid_payfast_source_ip", lambda _ip: True)
    monkeypatch.setattr(payment_routes.httpx, "post", lambda *args, **kwargs: SimpleNamespace(
        text="VALID", raise_for_status=lambda: None,
    ))
    with SessionLocal() as db:
        agency = db.query(m.User).filter_by(email="landlord@test.com").one()
        settings = m.AgencyPaymentSettings(agency_id=agency.id, payfast_merchant_id="12345678")
        attempt = m.MerchantVerificationAttempt(agency_id=agency.id,
                                                our_reference="LK-VERIFY-test", amount_cents=500)
        db.add_all([settings, attempt])
        db.commit()

    fields = {
        "merchant_id": "10000100", "pf_payment_id": "sandbox-verify-1",
        "payment_status": "COMPLETE", "amount_gross": "5.00",
        "m_payment_id": "LK-VERIFY-test",
    }
    fields["signature"] = payment_routes._sign(fields, "")
    response = client.post("/payments/payfast/notify", data=fields)

    assert response.status_code == 200
    with SessionLocal() as db:
        settings = db.query(m.AgencyPaymentSettings).one()
        attempt = db.query(m.MerchantVerificationAttempt).one()
        assert settings.verification_status == "verified"
        assert settings.verified_at is not None
        assert settings.payments_enabled is False
        assert attempt.status == "succeeded"
        assert attempt.provider_payment_id == "sandbox-verify-1"
