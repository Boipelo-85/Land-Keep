import hashlib
import hmac
import json
import time
from datetime import date

import httpx
import pytest
from sqlalchemy import select, func
from conftest import auth
from test_maintenance_chat import _tenant_with_lease
from app import models as m
from app.database import SessionLocal
from app.services import paystack


@pytest.fixture()
def payment_setup(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_PROVIDER', 'paystack')
    monkeypatch.setenv('PAYSTACK_SECRET_KEY', 'sk_test_unit_tests_only')
    monkeypatch.delenv('PAYSTACK_WEBHOOK_SECRET', raising=False)
    tenant_id, lease_id = _tenant_with_lease()
    with SessionLocal() as db:
        landlord = db.scalar(select(m.User).where(m.User.email == 'landlord@test.com'))
        db.add(m.PaystackSettings(agency_id=landlord.id, payments_enabled=True))
        charge = m.RentCharge(lease_id=lease_id, period=date(2026, 11, 1), due_date=date(2026, 11, 1), amount_due=7000)
        db.add(charge)
        db.commit()
        charge_id = charge.id
    calls = []
    def provider_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith('/initialize'):
            reference = kwargs['json']['reference']
            data = {'authorization_url': 'https://checkout.paystack.com/test-checkout', 'reference': reference}
        else:
            data = {'reference': url.rsplit('/', 1)[1], 'amount': 700000, 'currency': 'ZAR',
                    'domain': 'test', 'status': 'success', 'id': 123456789, 'channel': 'card'}
        return httpx.Response(200, json={'status': True, 'data': data}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, 'request', provider_request)
    return charge_id, auth(client, 'tenant-chat@test.com'), calls


def start(client, setup):
    charge_id, headers, _ = setup
    result = client.post(f'/payments/{charge_id}/checkout', headers=headers)
    assert result.status_code == 200, result.text
    return result.json()['reference']


def test_paystack_checkout_and_verified_settlement(client, payment_setup):
    charge_id, headers, calls = payment_setup
    reference = start(client, payment_setup)
    payload = calls[0][2]['json']
    assert payload['amount'] == 700000 and payload['currency'] == 'ZAR'
    assert payload['email'] == 'tenant-chat@test.com'
    assert 'subaccount' not in payload  # All rent goes to the one platform account.
    assert client.get('/payments/mine', headers=headers).json()['charges'][0]['outstanding'] == 7000
    resumed = client.post(f'/payments/{charge_id}/checkout', headers=headers)
    assert resumed.status_code == 200 and resumed.json()['reference'] == reference
    assert len(calls) == 1
    result = client.post(f'/payments/paystack/verify/{reference}', headers=headers)
    assert result.json()['status'] == 'succeeded'
    assert client.post(f'/payments/paystack/verify/{reference}', headers=headers).json()['status'] == 'succeeded'
    assert client.get('/payments/mine', headers=headers).json()['charges'] == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count(m.Payment.id))) == 1
        assert db.scalar(select(m.Payment)).provider == 'paystack'
    admin = client.get('/payments/paystack/admin', headers=auth(client, 'landlord@test.com')).json()
    assert admin['charges'][0]['outstanding'] == 0
    assert admin['attempts'][0]['status'] == 'succeeded'
    other = client.get('/payments/paystack/admin', headers=auth(client, 'other@test.com')).json()
    assert other['charges'] == [] and other['attempts'] == []


@pytest.mark.parametrize('field,value', [('amount', 1), ('currency', 'NGN'), ('domain', 'live'), ('reference', 'another')])
def test_wrong_details_never_credit_rent(client, payment_setup, monkeypatch, field, value):
    reference = start(client, payment_setup)
    data = {'reference': reference, 'amount': 700000, 'currency': 'ZAR', 'domain': 'test', 'status': 'success', 'id': 42}
    data[field] = value
    monkeypatch.setattr(paystack, 'verify', lambda ref: data)
    assert client.post(f'/payments/paystack/verify/{reference}', headers=payment_setup[1]).status_code == 400
    with SessionLocal() as db:
        assert db.scalar(select(func.count(m.Payment.id))) == 0


def test_webhook_signature_replay_and_permissions(client, payment_setup):
    reference = start(client, payment_setup)
    body = json.dumps({'event': 'charge.success', 'data': {'reference': reference}}).encode()
    assert client.post('/payments/paystack/webhook', content=body).status_code == 401
    signature = hmac.new(b'sk_test_unit_tests_only', body, hashlib.sha512).hexdigest()
    for _ in range(2):
        assert client.post('/payments/paystack/webhook', content=body, headers={'x-paystack-signature': signature}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count(m.Payment.id))) == 1
    assert client.get('/payments/paystack/admin', headers=payment_setup[1]).status_code == 403
    assert client.post(f'/payments/paystack/verify/{reference}', headers=auth(client, 'landlord@test.com')).status_code == 403
    new = client.post('/auth/register', json={'full_name': 'Another Tenant', 'email': 'another@test.com', 'password': 'password123'}).json()
    assert client.post(f'/payments/paystack/verify/{reference}', headers={'Authorization': 'Bearer ' + new['token']}).status_code == 404


def test_modern_signature_timestamp_and_no_downgrade(monkeypatch):
    monkeypatch.setenv('PAYSTACK_WEBHOOK_SECRET', 'whsec_test_secret')
    body = b'{"event":"ping"}'
    timestamp = str(int(time.time()))
    signature = hmac.new(b'whsec_test_secret', timestamp.encode() + b'.' + body, hashlib.sha512).hexdigest()
    assert paystack.valid_signature(body, {'paystack-signature': f't={timestamp},v1=whk_test:{signature}'})
    assert not paystack.valid_signature(body + b' ', {'paystack-signature': f't={timestamp},v1=whk_test:{signature}'})
    assert not paystack.valid_signature(body, {'paystack-signature': f't=1,v1=whk_test:{signature}'})
    assert not paystack.valid_signature(body, {'x-paystack-signature': signature})


def test_enable_requires_landlord_password_and_configuration(client, payment_setup, monkeypatch):
    landlord = auth(client, 'landlord@test.com')
    body = {'payments_enabled': False, 'current_password': 'wrong'}
    assert client.put('/payments/paystack/settings', headers=landlord, json=body).status_code == 403
    body['current_password'] = 'password123'
    assert client.put('/payments/paystack/settings', headers=landlord, json=body).status_code == 200
    assert client.post(f'/payments/{payment_setup[0]}/checkout', headers=payment_setup[1]).status_code == 409
    monkeypatch.delenv('PAYSTACK_SECRET_KEY')
    body['payments_enabled'] = True
    assert client.put('/payments/paystack/settings', headers=landlord, json=body).status_code == 409


def test_pending_verification_does_not_credit_rent(client, payment_setup, monkeypatch):
    reference = start(client, payment_setup)
    monkeypatch.setattr(paystack, 'verify', lambda ref: {'reference': ref, 'amount': 700000, 'currency': 'ZAR', 'domain': 'test', 'status': 'pending'})
    response = client.post(f'/payments/paystack/verify/{reference}', headers=payment_setup[1])
    assert response.json()['status'] == 'pending'
    with SessionLocal() as db:
        assert db.scalar(select(func.count(m.Payment.id))) == 0

def test_failed_initialization_is_retryable_but_timeout_is_not_duplicated(client, payment_setup, monkeypatch):
    def rejected(*args):
        raise paystack.PaystackRejected('Invalid gateway configuration')
    monkeypatch.setattr(paystack, 'initialize', rejected)
    charge_id, headers, _ = payment_setup
    assert client.post(f'/payments/{charge_id}/checkout', headers=headers).status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(m.PaymentAttempt)).status == 'failed'
    def timeout(*args):
        raise paystack.PaymentProviderError('Provider timeout')
    monkeypatch.setattr(paystack, 'initialize', timeout)
    assert client.post(f'/payments/{charge_id}/checkout', headers=headers).status_code == 503
    assert client.post(f'/payments/{charge_id}/checkout', headers=headers).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count(m.PaymentAttempt.id))) == 2
        assert db.scalar(select(func.count(m.Payment.id))) == 0


def test_database_prevents_concurrent_open_checkouts(client, payment_setup):
    from sqlalchemy.exc import IntegrityError
    start(client, payment_setup)
    with SessionLocal() as db:
        attempt = db.scalar(select(m.PaymentAttempt))
        db.add(m.PaymentAttempt(agency_id=attempt.agency_id, tenant_id=attempt.tenant_id,
            lease_id=attempt.lease_id, rent_record_id=attempt.rent_record_id, charge_id=attempt.charge_id,
            amount_cents=attempt.amount_cents, currency='ZAR', provider='paystack', status='pending',
            our_reference='another-reference', payment_reference='another-reference', recipient_merchant_id='platform'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_checkout_destination_and_live_callback_are_validated(monkeypatch):
    monkeypatch.setenv('PAYSTACK_SECRET_KEY', 'sk_test_only')
    monkeypatch.setattr(paystack, 'request', lambda *a: {'authorization_url': 'https://attacker.example/checkout', 'reference': 'LK-test'})
    with pytest.raises(paystack.PaymentProviderError, match='destination'):
        paystack.initialize('LK-test', 700000, 'user@example.test')
    monkeypatch.setenv('PAYSTACK_SECRET_KEY', 'sk_live_only')
    monkeypatch.setenv('PAYSTACK_CALLBACK_URL', 'http://localhost:5173/pay-rent')
    with pytest.raises(paystack.PaymentProviderError, match='HTTPS'):
        paystack.initialize('LK-test', 700000, 'user@example.test')
