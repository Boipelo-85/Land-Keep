from datetime import date
from conftest import auth
from app import models as m
from app.database import SessionLocal
from test_maintenance_chat import _tenant_with_lease


def charge_for_tenant():
    _,lease_id=_tenant_with_lease()
    with SessionLocal() as db:
        charge=m.RentCharge(lease_id=lease_id,period=date(2026,11,1),due_date=date(2026,11,1),amount_due=7000)
        db.add(charge);db.commit();return charge.id


def test_unconfigured_checkout_has_clear_readiness_without_hiding_charge(client,monkeypatch):
    charge_id=charge_for_tenant()
    monkeypatch.delenv('PAYFAST_MERCHANT_ID',raising=False)
    headers=auth(client,'tenant-chat@test.com')
    response=client.get('/payments/mine',headers=headers)
    assert response.status_code==200
    charge=response.json()['charges'][0]
    assert charge['charge_id']==charge_id
    assert charge['checkout']['ready'] is False
    assert 'credentials' in charge['checkout']['reason']


def test_ready_checkout_posts_to_hosted_provider_and_does_not_mark_rent_paid(client,monkeypatch):
    charge_id=charge_for_tenant()
    monkeypatch.setenv('PAYFAST_MERCHANT_ID','10000100')
    monkeypatch.setenv('PAYFAST_MERCHANT_KEY','sandbox-key')
    monkeypatch.setenv('PAYFAST_MODE','sandbox')
    monkeypatch.setenv('PAYFAST_SPLIT_PAYMENTS_ENABLED','true')
    monkeypatch.setenv('LANDKEEP_PUBLIC_BASE_URL','')
    with SessionLocal() as db:
        landlord=db.query(m.User).filter_by(email='landlord@test.com').one()
        db.add(m.AgencyPaymentSettings(agency_id=landlord.id,payfast_merchant_id='10000200',verification_status='verified',payments_enabled=True))
        db.commit()
    headers=auth(client,'tenant-chat@test.com')
    assert client.get('/payments/mine',headers=headers).json()['charges'][0]['checkout']['ready'] is True
    response=client.post(f'/payments/{charge_id}/checkout',headers=headers)
    assert response.status_code==200
    result=response.json()
    assert result['action']=='https://sandbox.payfast.co.za/eng/process'
    assert result['fields']['amount']=='7000.00'
    assert result['fields']['return_url'].startswith('http://127.0.0.1:5173/')
    assert result['fields']['signature']
    assert not any(key in result['fields'] for key in ['card_number','cvv','bank_password'])
    assert client.get('/payments/mine',headers=headers).json()['charges'][0]['outstanding']==7000
