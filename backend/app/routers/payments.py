"""Tenant rent checkout using PayFast's hosted payment page and verified ITNs."""
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
import re
from urllib.parse import quote_plus

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import require_landlord, require_tenant
from ..security import verify_password
from ..services.money import cents_to_zar, zar_to_cents
from ..services.payment_providers import CheckoutRequest, PaymentProviderError, get_payment_provider, is_valid_payfast_source_ip
from ..services.reminder_senders import build_sender, send_with_retries

router = APIRouter(prefix="/payments", tags=["payments"])


class PayFastSettingsIn(BaseModel):
    payfast_merchant_id: str | None = None
    current_password: str = Field(min_length=1, max_length=100)
    payments_enabled: bool | None = None

    @field_validator("payfast_merchant_id")
    @classmethod
    def validate_merchant_id(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not re.fullmatch(r"[0-9]{8}", value, flags=re.ASCII):
            raise ValueError("Enter the 8-digit PayFast merchant ID from your account settings. Do not enter a merchant key or passphrase.")
        # Reject obvious keys/passphrases (they're longer or contain non-digits)
        if len(value) > 32 or not value.isdigit():
            raise ValueError("Enter the 8-digit PayFast merchant ID from your account settings. Do not enter a merchant key or passphrase.")
        return value


def _mask_merchant_id(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:4]}****"


def _agency_settings(db: Session, agency_id: int) -> m.AgencyPaymentSettings | None:
    return db.scalar(select(m.AgencyPaymentSettings).where(
        m.AgencyPaymentSettings.agency_id == agency_id
    ))


def _notify_merchant_change(db: Session, user: m.User, old_masked: str | None, new_masked: str) -> None:
    subject = "PayFast merchant account changed"
    body = (f"Hello {user.full_name}, the PayFast recipient merchant ID for your Land-Keep account "
            f"was changed from {old_masked or 'none'} to {new_masked}. If you did not make this change, "
            "please contact Land-Keep support.")
    status = "sent"
    try:
        send_with_retries(build_sender("email"), user.email, subject, body)
    except Exception:
        status = "failed"
    db.add(m.Notification(user_id=user.id, channel="email", template="payment_merchant_changed",
                          subject=subject, body=body, status=status))


@router.get("/settings")
def get_landlord_payment_settings(user: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    legacy = db.scalar(select(m.LandlordPaymentSettings).where(
        m.LandlordPaymentSettings.landlord_id == user.id
    ))
    settings = _agency_settings(db, user.id)
    merchant_id = settings.payfast_merchant_id if settings and settings.payfast_merchant_id else (legacy.payfast_merchant_id if legacy else None)
    return {"payfast_merchant_id_masked": _mask_merchant_id(merchant_id),
            "verification_status": settings.verification_status if settings else "not_verified",
            "verified_at": settings.verified_at if settings else None,
            "payments_enabled": settings.payments_enabled if settings else False,
            "split_payments_ready": os.getenv("PAYFAST_SPLIT_PAYMENTS_ENABLED", "false").lower() == "true"}


@router.put("/settings")
def update_landlord_payment_settings(body: PayFastSettingsIn,
                                     user: m.User = Depends(require_landlord),
                                     db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Your password is incorrect. Please try again.")
    legacy = db.scalar(select(m.LandlordPaymentSettings).where(
        m.LandlordPaymentSettings.landlord_id == user.id
    ))
    settings = _agency_settings(db, user.id)
    if settings is None:
        settings = m.AgencyPaymentSettings(agency_id=user.id)
        db.add(settings)
        db.flush()
    old_id = settings.payfast_merchant_id or (legacy.payfast_merchant_id if legacy else None)
    if settings.payfast_merchant_id is None and old_id is not None:
        settings.payfast_merchant_id = old_id
    changed = body.payfast_merchant_id is not None and body.payfast_merchant_id != old_id
    if changed:
        old_masked = _mask_merchant_id(old_id)
        new_id = body.payfast_merchant_id
        # Merchant ID format does not establish sandbox/live mode. Use the explicit
        # provider environment and verified payment, not an ID-prefix heuristic.
        settings.payfast_merchant_id = new_id
        settings.verification_status = "not_verified"
        settings.verified_at = None
        settings.verified_by_user_id = None
        settings.payments_enabled = False
        audit = m.AgencyPaymentSettingsAudit(
            agency_id=user.id, changed_by_user_id=user.id,
            old_merchant_id_masked=old_masked,
            new_merchant_id_masked=_mask_merchant_id(new_id),
        )
        db.add(audit)
        if legacy is None:
            legacy = m.LandlordPaymentSettings(landlord_id=user.id, payfast_merchant_id=new_id)
            db.add(legacy)
        else:
            legacy.payfast_merchant_id = new_id
        _notify_merchant_change(db, user, old_masked, _mask_merchant_id(new_id))
    elif old_id is None:
        raise HTTPException(422, "Enter your PayFast merchant ID before saving payment settings.")

    if body.payments_enabled is True and settings.verification_status != "verified":
        raise HTTPException(409, "Verify your PayFast account before enabling tenant payments.")
    if body.payments_enabled is not None:
        settings.payments_enabled = body.payments_enabled
    db.commit()
    return {"payfast_merchant_id_masked": _mask_merchant_id(settings.payfast_merchant_id),
            "verification_status": settings.verification_status,
            "verified_at": settings.verified_at,
            "payments_enabled": settings.payments_enabled}


@router.post("/settings/verify")
def start_payfast_account_verification(body: dict,
                                       user: m.User = Depends(require_landlord),
                                       db: Session = Depends(get_db)):
    password = body.get("current_password", "")
    if not isinstance(password, str) or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Your password is incorrect. Please try again.")
    settings = _agency_settings(db, user.id)
    if settings is None or not settings.payfast_merchant_id:
        raise HTTPException(409, "Save your PayFast merchant ID before starting verification.")
    if settings.verification_status == "verified":
        return {"verification_status": "verified", "message": "This account is already verified."}
    if os.getenv("PAYMENT_PROVIDER", "mock").lower() != "payfast":
        raise HTTPException(503, "Switch PAYMENT_PROVIDER to payfast and configure PayFast Sandbox to run the R5 verification payment.")
    _merchant_id, _merchant_key, _passphrase, _host = _config()
    reference = f"LK-VERIFY-{os.urandom(12).hex()}"
    attempt = m.MerchantVerificationAttempt(agency_id=user.id, our_reference=reference, amount_cents=500)
    db.add(attempt)
    db.commit()
    base_url = (os.getenv("LANDKEEP_PUBLIC_BASE_URL", "").strip() or "http://127.0.0.1:5173").rstrip("/")
    try:
        provider = get_payment_provider("payfast")
        result = provider.create_checkout(CheckoutRequest(
            our_reference=reference, amount_cents=500,
            item_name="Land-Keep merchant account verification", buyer_name=user.full_name,
            buyer_email=user.email, return_url=f"{base_url}/landlord/payments?verification=pending",
            cancel_url=f"{base_url}/landlord/payments?verification=cancelled",
            notify_url=os.getenv("PAYFAST_NOTIFY_URL", f"{base_url}/api/payments/payfast/notify"),
            split_merchant_id=settings.payfast_merchant_id, platform_fee_cents=0,
        ))
    except PaymentProviderError as exc:
        attempt.status = "failed"
        db.commit()
        raise HTTPException(503, str(exc)) from exc
    return {"action": result.redirect_url, "fields": result.fields,
            "verification_status": "not_verified", "amount_cents": 500,
            "message": "Complete the R5.00 hosted checkout. Verification updates only after PayFast confirms the payment."}


def _config():
    merchant_id = os.getenv("PAYFAST_MERCHANT_ID", "").strip()
    merchant_key = os.getenv("PAYFAST_MERCHANT_KEY", "").strip()
    if not merchant_id or not merchant_key:
        raise HTTPException(503, "Online rent payments are not configured yet. Please contact your landlord.")
    if os.getenv("PAYFAST_SPLIT_PAYMENTS_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Landlord payouts are not enabled for this payment account yet.")
    mode = os.getenv("PAYFAST_MODE", "").strip().lower()
    sandbox = (mode == "sandbox") if mode in {"sandbox", "live"} else os.getenv("PAYFAST_SANDBOX", "true").lower() == "true"
    host = "sandbox.payfast.co.za" if sandbox else "www.payfast.co.za"
    return merchant_id, merchant_key, os.getenv("PAYFAST_PASSPHRASE", "").strip(), host


def _sign(fields: dict[str, str], passphrase: str) -> str:
    parts = [f"{key}={quote_plus(str(value).strip())}" for key, value in fields.items() if value != ""]
    if passphrase:
        parts.append(f"passphrase={quote_plus(passphrase)}")
    return hashlib.md5("&".join(parts).encode("utf-8")).hexdigest()


def _balance(db: Session, charge: m.RentCharge) -> Decimal:
    total_paid_cents = int(db.scalar(select(func.coalesce(func.sum(m.Payment.amount_cents), 0)).where(
        m.Payment.charge_id == charge.id
    )) or 0)
    return cents_to_zar(max(0, zar_to_cents(charge.amount_due) - total_paid_cents))


def payment_readiness(db: Session, landlord_id: int) -> dict:
    if os.getenv("PAYMENT_PROVIDER", "payfast").lower() == "paystack":
        from .paystack import readiness
        return readiness(db, landlord_id)
    try:
        mode = get_payment_provider("payfast").mode
    except PaymentProviderError:
        return {"provider": "payfast", "mode": "unknown", "ready": False, "reason": "PayFast mode must be sandbox or live."}
    result = {"provider": "payfast", "mode": mode, "ready": False}
    if not os.getenv("PAYFAST_MERCHANT_ID", "").strip() or not os.getenv("PAYFAST_MERCHANT_KEY", "").strip():
        return {**result, "reason": "Platform PayFast credentials have not been configured. Your landlord needs payment setup completed first."}
    if os.getenv("PAYFAST_SPLIT_PAYMENTS_ENABLED", "false").lower() != "true":
        return {**result, "reason": "PayFast landlord payouts have not been enabled for this platform."}
    settings = _agency_settings(db, landlord_id)
    if not settings or not settings.payfast_merchant_id or settings.verification_status != "verified" or not settings.payments_enabled:
        return {**result, "reason": "Your landlord must verify and enable their PayFast account in Payment setup."}
    return {**result, "ready": True, "reason": None}


def _charge_view(db: Session, charge: m.RentCharge, lease: m.Lease) -> dict:
    unit = db.get(m.Unit, lease.unit_id)
    prop = db.get(m.Property, unit.property_id)
    return {"charge_id": charge.id, "lease_id": lease.id, "period": charge.period.strftime("%Y-%m"),
            "due_date": charge.due_date, "property": prop.name, "unit": unit.unit_number,
            "amount_due": float(charge.amount_due), "amount_paid": float(charge.amount_due) - float(_balance(db, charge)),
            "outstanding": float(_balance(db, charge)), "checkout": payment_readiness(db, prop.landlord_id)}


@router.get("/mine")
def my_rent_charges(user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    rows = db.execute(select(m.RentCharge, m.Lease).join(m.Lease, m.Lease.id == m.RentCharge.lease_id)
                      .where(m.Lease.tenant_id == user.id, m.Lease.status == "active")
                      .order_by(m.RentCharge.due_date.desc())).all()
    charges = [_charge_view(db, charge, lease) for charge, lease in rows]
    charges = [charge for charge in charges if charge["outstanding"] > 0.009]
    attempts = db.scalars(select(m.PaymentAttempt).where(m.PaymentAttempt.tenant_id == user.id)
                          .order_by(m.PaymentAttempt.created_at.desc()).limit(20)).all()
    return {"charges": charges, "attempts": [
        {"reference": a.our_reference, "charge_id": a.rent_record_id,
         "amount": float(cents_to_zar(a.amount_cents)), "status": a.status, "provider": a.provider,
         "created_at": a.created_at, "paid_at": a.completed_at} for a in attempts
    ]}


@router.post("/{charge_id}/checkout")
def create_checkout(charge_id: int, user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    if os.getenv("PAYMENT_PROVIDER", "payfast").lower() == "paystack":
        from .paystack import checkout
        return checkout(db, charge_id, user)
    merchant_id, merchant_key, passphrase, host = _config()
    row = db.execute(select(m.RentCharge, m.Lease).join(m.Lease, m.Lease.id == m.RentCharge.lease_id)
                     .where(m.RentCharge.id == charge_id, m.Lease.tenant_id == user.id,
                            m.Lease.status == "active")).first()
    if row is None:
        raise HTTPException(404, "Rent charge not found")
    charge, lease = row
    landlord_id = db.scalar(select(m.Property.landlord_id).join(
        m.Unit, m.Unit.property_id == m.Property.id
    ).where(m.Unit.id == lease.unit_id))
    recipient = _agency_settings(db, landlord_id)
    if recipient is None or recipient.verification_status != "verified" or not recipient.payments_enabled:
        raise HTTPException(409, "Online rent payments are unavailable until your landlord verifies and enables their PayFast account.")
    if not recipient.payfast_merchant_id:
        raise HTTPException(409, "Your landlord has not finished setting up online rent payments yet.")
    outstanding = _balance(db, charge).quantize(Decimal("0.01"))
    if outstanding <= 0:
        raise HTTPException(409, "This rent charge is already paid")
    if outstanding < Decimal("5.00"):
        raise HTTPException(400, "PayFast online payments require at least R5.00")

    reference = f"LK-{os.urandom(12).hex()}"
    amount_cents = zar_to_cents(outstanding)
    attempt = m.PaymentAttempt(
        agency_id=landlord_id, tenant_id=user.id, lease_id=lease.id,
        rent_record_id=charge.id, amount_cents=amount_cents,
        platform_fee_cents=0, currency="ZAR", provider="payfast",
        our_reference=reference, payment_reference=reference,
        charge_id=charge.id, recipient_merchant_id=recipient.payfast_merchant_id,
        status="initiated",
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    base_url = (os.getenv("LANDKEEP_PUBLIC_BASE_URL", "").strip() or "http://127.0.0.1:5173").rstrip("/")
    try:
        provider = get_payment_provider("payfast")
        result = provider.create_checkout(CheckoutRequest(
            our_reference=attempt.our_reference, amount_cents=attempt.amount_cents,
            item_name=f"LandKeep rent {charge.period:%B %Y}", buyer_name=user.full_name, buyer_email=user.email,
            return_url=os.getenv("PAYFAST_RETURN_URL", "").strip() or f"{base_url}/pay-rent?payment=return",
            cancel_url=os.getenv("PAYFAST_CANCEL_URL", "").strip() or f"{base_url}/pay-rent?payment=cancelled",
            notify_url=os.getenv("PAYFAST_NOTIFY_URL", "").strip() or f"{base_url}/api/payments/payfast/notify",
            split_merchant_id=attempt.recipient_merchant_id, platform_fee_cents=0))
    except PaymentProviderError as exc:
        attempt.status = "failed"
        db.commit()
        raise HTTPException(503, str(exc)) from exc
    return {"action": result.redirect_url, "fields": result.fields, "provider": "payfast",
            "mode": provider.mode}



@router.get("/payfast/notify")
def payfast_notify_health():
    return {"status": "ready", "method": "POST"}


@router.post("/payfast/notify")
async def payfast_notify(request: Request, db: Session = Depends(get_db)):
    merchant_id, _merchant_key, passphrase, host = _config()
    form = await request.form()
    raw = {str(key): str(value) for key, value in form.multi_items() if isinstance(value, str)}
    supplied_signature = raw.pop("signature", "")
    if not supplied_signature or not hmac.compare_digest(supplied_signature, _sign(raw, passphrase)):
        raise HTTPException(400, "Invalid PayFast signature")
    if raw.get("merchant_id") != merchant_id:
        raise HTTPException(400, "Payment merchant does not match")
    source_ip = request.client.host if request.client else ""
    if not is_valid_payfast_source_ip(source_ip):
        raise HTTPException(400, "PayFast notification came from an untrusted source")

    reference = raw.get("m_payment_id", "")
    verification = db.scalar(select(m.MerchantVerificationAttempt).where(
        m.MerchantVerificationAttempt.our_reference == reference
    )) if reference.startswith("LK-VERIFY-") else None
    if reference.startswith("LK-VERIFY-") and verification is None:
        raise HTTPException(404, "Merchant verification reference not found")
    if verification is not None:
        if verification.status == "succeeded":
            return {"status": "ok"}
        try:
            gross_cents = zar_to_cents(Decimal(raw.get("amount_gross", "0")))
        except (InvalidOperation, ValueError):
            raise HTTPException(400, "Invalid verification payment amount")
        if gross_cents != verification.amount_cents:
            verification.status = "failed"
            db.commit()
            raise HTTPException(400, "Verification payment amount did not match R5.00")
        if raw.get("payment_status") != "COMPLETE":
            verification.status = "failed" if raw.get("payment_status") in {"FAILED", "CANCELLED"} else "pending"
            db.commit()
            return {"status": "ignored"}
        try:
            response = httpx.post(
                f"https://{host}/eng/query/validate",
                data=raw | {"signature": supplied_signature}, timeout=12.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Could not verify the account test payment with PayFast") from exc
        if response.text.strip() != "VALID":
            raise HTTPException(400, "PayFast did not confirm the account test payment")
        verification.status = "succeeded"
        verification.provider_payment_id = raw.get("pf_payment_id") or reference
        verification.completed_at = m.utcnow()
        settings = _agency_settings(db, verification.agency_id)
        if settings is None:
            raise HTTPException(409, "Payment settings were removed before verification completed")
        settings.verification_status = "verified"
        settings.verified_at = m.utcnow()
        settings.verified_by_user_id = verification.agency_id
        db.commit()
        return {"status": "ok"}

    attempt = db.scalar(select(m.PaymentAttempt).where(m.PaymentAttempt.our_reference == reference))
    if attempt is None:
        raise HTTPException(404, "Payment reference not found")
    if attempt.status == "succeeded":
        return {"status": "ok"}
    try:
        gross = Decimal(raw.get("amount_gross", "0")).quantize(Decimal("0.01"))
        expected = cents_to_zar(attempt.amount_cents).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise HTTPException(400, "Invalid payment amount")
    if gross != expected:
        raise HTTPException(400, "Payment amount does not match the rent balance")
    if raw.get("payment_status") != "COMPLETE":
        attempt.status = "failed" if raw.get("payment_status") == "CANCELLED" else attempt.status
        db.commit()
        return {"status": "ignored"}

    # Verify the notification independently with PayFast; browser returns never settle a charge.
    try:
        response = httpx.post(f"https://{host}/eng/query/validate", data=raw | {"signature": supplied_signature}, timeout=12.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not verify payment with PayFast") from exc
    if response.text.strip() != "VALID":
        raise HTTPException(400, "PayFast rejected the payment notification")

    provider_id = raw.get("pf_payment_id") or reference
    existing = db.scalar(select(m.Payment).where(m.Payment.gateway_attempt_id == attempt.id))
    if existing is None:
        db.add(m.Payment(
            charge_id=attempt.rent_record_id, amount_cents=attempt.amount_cents,
            paid_at=m.utcnow(), method="payfast", provider="payfast",
            reference=attempt.our_reference, provider_payment_id=provider_id,
            gateway_attempt_id=attempt.id,
        ))
    attempt.provider_payment_id = provider_id
    attempt.provider_transaction_id = provider_id
    attempt.status = "succeeded"
    attempt.completed_at = m.utcnow()
    attempt.paid_at = m.utcnow()
    attempt.updated_at = m.utcnow()
    db.commit()
    return {"status": "ok"}
