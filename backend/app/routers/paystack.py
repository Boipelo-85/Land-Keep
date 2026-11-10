"""Tenant payment verification and landlord administration for one LandKeep account."""
import json
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from .. import models as m
from ..database import get_db
from ..deps import require_landlord, require_tenant
from ..security import verify_password
from ..services import paystack
from ..services.money import zar_to_cents, cents_to_zar
from ..services.payment_providers import PaymentProviderError
from .payments import _balance, _charge_view

router = APIRouter(prefix='/payments/paystack', tags=['paystack'])


def readiness(db, landlord_id):
    settings = db.scalar(select(m.PaystackSettings).where(m.PaystackSettings.agency_id == landlord_id))
    result = {'provider': 'paystack', 'mode': paystack.mode(), 'ready': False}
    try:
        paystack.secret_key()
    except PaymentProviderError as exc:
        return {**result, 'reason': str(exc)}
    if not settings or not settings.payments_enabled:
        return {**result, 'reason': 'Your landlord needs to enable online rent payments.'}
    return {**result, 'ready': True, 'reason': None}


def checkout(db, charge_id, user):
    row = db.execute(select(m.RentCharge, m.Lease).join(m.Lease, m.Lease.id == m.RentCharge.lease_id)
        .where(m.RentCharge.id == charge_id, m.Lease.tenant_id == user.id, m.Lease.status == 'active')
        .with_for_update()).first()
    if row is None:
        raise HTTPException(404, 'Rent charge not found')
    charge, lease = row
    unit = db.get(m.Unit, lease.unit_id)
    landlord_id = db.get(m.Property, unit.property_id).landlord_id
    available = readiness(db, landlord_id)
    if not available['ready']:
        raise HTTPException(409, available['reason'])
    amount = zar_to_cents(_balance(db, charge))
    if amount <= 0:
        raise HTTPException(409, 'This rent charge is already paid')
    pending = db.scalar(select(m.PaymentAttempt).where(m.PaymentAttempt.rent_record_id == charge.id,
        m.PaymentAttempt.provider == 'paystack', m.PaymentAttempt.status.in_(['initiated', 'pending'])))
    if pending and pending.checkout_url:
        return {'provider': 'paystack', 'method': 'GET', 'action': pending.checkout_url,
                'reference': pending.our_reference, 'mode': paystack.mode()}
    if pending:
        raise HTTPException(409, 'A payment is already in progress. Check its status in Recent payment attempts before trying again.')
    reference = 'LK-PS-' + os.urandom(16).hex()
    attempt = m.PaymentAttempt(agency_id=landlord_id, tenant_id=user.id, lease_id=lease.id,
        rent_record_id=charge.id, charge_id=charge.id, amount_cents=amount, platform_fee_cents=0,
        currency='ZAR', provider='paystack', our_reference=reference, payment_reference=reference,
        recipient_merchant_id='platform', status='initiated')
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A payment is already being opened. Refresh and check its status before trying again.")
    try:
        url = paystack.initialize(reference, amount, user.email)
    except PaymentProviderError as exc:
        if isinstance(exc, paystack.PaystackRejected):
            attempt.status = 'failed'
            db.commit()
        # Initialization may have reached the provider despite a timeout. Verification
        # remains available, and a new checkout cannot silently double-charge the tenant.
        raise HTTPException(503, str(exc)) from exc
    attempt.checkout_url = url
    db.commit()
    return {'provider': 'paystack', 'method': 'GET', 'action': url, 'reference': reference, 'mode': paystack.mode()}


def settle(db, attempt):
    if attempt.status == 'succeeded':
        return {'status': 'succeeded', 'reference': attempt.our_reference}
    try:
        data = paystack.verify(attempt.our_reference)
    except PaymentProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    if (data.get('reference') != attempt.our_reference or type(data.get('amount')) is not int
        or data['amount'] != attempt.amount_cents or data.get('currency') != attempt.currency
        or data.get('domain') != paystack.mode()):
        raise HTTPException(400, 'Paystack payment details do not match the rent charge')
    status = data.get('status')
    # Re-load under a lock after the external request to serialize webhook/callback races.
    attempt = db.scalar(select(m.PaymentAttempt).where(m.PaymentAttempt.id == attempt.id)
        .with_for_update().execution_options(populate_existing=True))
    if attempt.status == 'succeeded':
        return {'status': 'succeeded', 'reference': attempt.our_reference}
    if status != 'success':
        next_status = {'failed': 'failed', 'abandoned': 'cancelled', 'reversed': 'reversed'}.get(status, 'pending')
        if next_status != 'pending' or attempt.status in {'initiated', 'pending'}:
            attempt.status = next_status
        db.commit()
        return {'status': attempt.status, 'reference': attempt.our_reference}
    provider_id = data.get('id')
    if not isinstance(provider_id, (str, int)) or isinstance(provider_id, bool) or not str(provider_id):
        raise HTTPException(400, 'Paystack did not provide a transaction ID')
    provider_id = str(provider_id)
    db.add(m.Payment(charge_id=attempt.rent_record_id, amount_cents=attempt.amount_cents,
        paid_at=m.utcnow(), method=str(data.get('channel') or 'paystack'), provider='paystack',
        reference=attempt.our_reference, provider_payment_id=provider_id, gateway_attempt_id=attempt.id))
    attempt.status = 'succeeded'
    attempt.provider_payment_id = provider_id
    attempt.provider_transaction_id = provider_id
    attempt.completed_at = attempt.paid_at = attempt.updated_at = m.utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(m.Payment).where(m.Payment.gateway_attempt_id == attempt.id))
        if existing is None:
            raise HTTPException(409, 'Payment transaction is already linked to another attempt')
    return {'status': 'succeeded', 'reference': attempt.our_reference}


@router.post('/verify/{reference}')
def verify_payment(reference: str, user=Depends(require_tenant), db: Session = Depends(get_db)):
    attempt = db.scalar(select(m.PaymentAttempt).where(m.PaymentAttempt.our_reference == reference,
        m.PaymentAttempt.provider == 'paystack', m.PaymentAttempt.tenant_id == user.id))
    if attempt is None:
        raise HTTPException(404, 'Payment not found')
    return settle(db, attempt)


@router.post('/webhook')
async def webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(413, 'Webhook payload too large')
    try:
        valid = paystack.valid_signature(body, request.headers)
    except PaymentProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not valid:
        raise HTTPException(401, 'Invalid Paystack signature')
    try:
        event = json.loads(body)
        if not isinstance(event, dict):
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid webhook payload')
    if event.get('event') != 'charge.success':
        return {'status': 'ignored'}
    data = event.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('reference'), str):
        raise HTTPException(400, 'Missing payment reference')
    attempt = db.scalar(select(m.PaymentAttempt).where(m.PaymentAttempt.our_reference == data['reference'],
        m.PaymentAttempt.provider == 'paystack'))
    if attempt is None:
        return {'status': 'ignored'}
    return await run_in_threadpool(settle, db, attempt)


class SettingsIn(BaseModel):
    payments_enabled: bool
    current_password: str = Field(min_length=1, max_length=100)


@router.get('/admin')
def admin(user=Depends(require_landlord), db: Session = Depends(get_db)):
    settings = db.scalar(select(m.PaystackSettings).where(m.PaystackSettings.agency_id == user.id))
    rows = db.execute(select(m.RentCharge, m.Lease).join(m.Lease, m.Lease.id == m.RentCharge.lease_id)
        .join(m.Unit, m.Unit.id == m.Lease.unit_id).join(m.Property, m.Property.id == m.Unit.property_id)
        .where(m.Property.landlord_id == user.id).order_by(m.RentCharge.due_date.desc())).all()
    charges = [{**_charge_view(db, charge, lease), 'tenant': db.get(m.User, lease.tenant_id).full_name,
                'reminders_paused': bool(lease.reminders_paused)} for charge, lease in rows]
    attempts = db.scalars(select(m.PaymentAttempt).where(m.PaymentAttempt.agency_id == user.id)
        .order_by(m.PaymentAttempt.created_at.desc()).limit(100)).all()
    return {'gateway': readiness(db, user.id), 'selected_provider': os.getenv('PAYMENT_PROVIDER', 'payfast'),
        'payments_enabled': bool(settings and settings.payments_enabled),
        'charges': charges, 'attempts': [{'reference': a.our_reference, 'provider': a.provider,
        'tenant': db.get(m.User, a.tenant_id).full_name, 'amount': float(cents_to_zar(a.amount_cents)),
        'status': a.status, 'created_at': a.created_at, 'paid_at': a.completed_at} for a in attempts]}


@router.put('/settings')
def save_settings(body: SettingsIn, user=Depends(require_landlord), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, 'Your password is incorrect')
    if body.payments_enabled:
        try:
            paystack.secret_key()
        except PaymentProviderError as exc:
            raise HTTPException(409, str(exc)) from exc
    settings = db.scalar(select(m.PaystackSettings).where(m.PaystackSettings.agency_id == user.id))
    if settings is None:
        settings = m.PaystackSettings(agency_id=user.id)
        db.add(settings)
    settings.payments_enabled = body.payments_enabled
    db.add(m.Notification(user_id=user.id, channel='in_app', template='paystack_settings_changed',
        subject='Online rent payment settings changed', body=f'Paystack payments enabled: {body.payments_enabled}', status='recorded'))
    db.commit()
    return {'payments_enabled': settings.payments_enabled}
