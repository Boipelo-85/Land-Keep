"""Payment gateway adapters. Provider code never receives or stores card data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import ipaddress
import json
import os
from typing import Mapping, Protocol
from urllib.parse import quote_plus

import httpx


class PaymentProviderError(RuntimeError):
    """A safe provider-layer error; callers should log a reference, not card data."""


@dataclass(frozen=True)
class CheckoutRequest:
    our_reference: str
    amount_cents: int
    item_name: str
    buyer_name: str
    buyer_email: str
    return_url: str
    cancel_url: str
    notify_url: str
    split_merchant_id: str | None = None
    platform_fee_cents: int = 0


@dataclass(frozen=True)
class CheckoutResult:
    redirect_url: str
    fields: dict[str, str]
    simulated_status: str | None = None


@dataclass(frozen=True)
class ParsedNotification:
    our_reference: str
    provider_payment_id: str
    status: str
    amount_cents: int
    merchant_id: str
    payment_method: str | None
    fields: dict[str, str]


@dataclass(frozen=True)
class VerificationResult:
    signature_valid: bool
    ip_valid: bool
    server_confirmed: bool
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.signature_valid and self.ip_valid and self.server_confirmed


@dataclass(frozen=True)
class RefundResult:
    succeeded: bool
    provider_reference: str | None = None
    reason: str | None = None


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult: ...
    def parse_notification(self, fields: Mapping[str, str]) -> ParsedNotification: ...
    def verify_payment(self, notification: ParsedNotification, source_ip: str) -> VerificationResult: ...
    def refund(self, provider_payment_id: str, amount_cents: int, reason: str) -> RefundResult: ...


# PayFast's published ranges for payment notifications; refresh against their
# ITN documentation rather than assuming these are immutable.
PAYFAST_SOURCE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "197.97.145.144/28",
    "41.74.179.192/27",
    "102.216.36.0/28",
    "102.216.36.128/28",
    "144.126.193.139/32",
))

CHECKOUT_SIGNATURE_ORDER = (
    "merchant_id", "merchant_key", "return_url", "cancel_url", "notify_url",
    "name_first", "name_last", "email_address", "cell_number", "amount",
    "item_name", "item_description", "m_payment_id", "custom_int1", "custom_int2",
    "custom_int3", "custom_int4", "custom_int5", "custom_str1", "custom_str2",
    "custom_str3", "custom_str4", "custom_str5", "email_confirmation", "confirmation_address",
)


def _urlencode(value: str) -> str:
    # PHP urlencode-compatible: spaces as + and uppercase percent escapes.
    return quote_plus(value.strip(), safe="")


def _amount_zar(amount_cents: int) -> str:
    if amount_cents < 0:
        raise ValueError("Payment amount cannot be negative")
    return f"{amount_cents // 100}.{amount_cents % 100:02d}"


def _checkout_signature(fields: Mapping[str, str], passphrase: str) -> str:
    pairs = [f"{key}={_urlencode(str(fields[key]))}" for key in CHECKOUT_SIGNATURE_ORDER
             if key in fields and str(fields[key]) != ""]
    if passphrase:
        pairs.append(f"passphrase={_urlencode(passphrase)}")
    return hashlib.md5("&".join(pairs).encode("utf-8")).hexdigest()


def _itn_signature(fields: Mapping[str, str], passphrase: str) -> str:
    # PayFast's ITN signature follows the submitted field order, excluding signature.
    pairs = [f"{key}={_urlencode(str(value))}" for key, value in fields.items()
             if key != "signature" and str(value) != ""]
    if passphrase:
        pairs.append(f"passphrase={_urlencode(passphrase)}")
    return hashlib.md5("&".join(pairs).encode("utf-8")).hexdigest()


def is_valid_payfast_source_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in PAYFAST_SOURCE_NETWORKS)


class PayfastProvider:
    name = "payfast"

    def __init__(self) -> None:
        self.merchant_id = os.getenv("PAYFAST_MERCHANT_ID", "").strip()
        self.merchant_key = os.getenv("PAYFAST_MERCHANT_KEY", "").strip()
        self.passphrase = os.getenv("PAYFAST_PASSPHRASE", "").strip()
        mode = os.getenv("PAYFAST_MODE", "").strip().lower()
        if not mode:
            mode = "sandbox" if os.getenv("PAYFAST_SANDBOX", "true").lower() == "true" else "live"
        if mode not in {"sandbox", "live"}:
            raise PaymentProviderError("PAYFAST_MODE must be sandbox or live")
        self.mode = mode
        self.process_url = ("https://sandbox.payfast.co.za/eng/process" if mode == "sandbox"
                            else "https://www.payfast.co.za/eng/process")
        self.validate_url = ("https://sandbox.payfast.co.za/eng/query/validate" if mode == "sandbox"
                             else "https://www.payfast.co.za/eng/query/validate")
        self.api_testing = mode == "sandbox"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if not self.merchant_id or not self.merchant_key:
            raise PaymentProviderError("PayFast merchant credentials are not configured")
        if self.mode == "live" and not all(url.startswith("https://") for url in (
            request.return_url, request.cancel_url, request.notify_url
        )):
            raise PaymentProviderError("Live PayFast return, cancel, and notify URLs must use HTTPS")
        parts = request.buyer_name.strip().split(maxsplit=1)
        fields = {
            "merchant_id": self.merchant_id,
            "merchant_key": self.merchant_key,
            "return_url": request.return_url,
            "cancel_url": request.cancel_url,
            "notify_url": request.notify_url,
            "name_first": parts[0][:100] if parts else "Tenant",
            "name_last": parts[1][:100] if len(parts) > 1 else "",
            "email_address": request.buyer_email[:100],
            "m_payment_id": request.our_reference,
            "amount": _amount_zar(request.amount_cents),
            "item_name": request.item_name[:100],
        }
        if request.split_merchant_id:
            recipient_cents = request.amount_cents - request.platform_fee_cents
            if recipient_cents < 0:
                raise PaymentProviderError("Platform fee cannot exceed the checkout amount")
            fields["setup"] = json.dumps({"split_payment": {
                "merchant_id": int(request.split_merchant_id),
                "amount": recipient_cents,
            }}, separators=(",", ":"))
        # PayFast explicitly excludes `setup` from its signature.
        fields["signature"] = _checkout_signature(fields, self.passphrase)
        return CheckoutResult(self.process_url, fields)

    def parse_notification(self, fields: Mapping[str, str]) -> ParsedNotification:
        clean = {str(key): str(value) for key, value in fields.items()}
        try:
            amount = Decimal(clean["amount_gross"]).quantize(Decimal("0.01"))
            amount_cents = int(amount * 100)
        except (KeyError, ArithmeticError, ValueError) as exc:
            raise PaymentProviderError("PayFast ITN is missing a valid amount") from exc
        status = clean.get("payment_status", "").strip().upper()
        status_map = {"COMPLETE": "succeeded", "CANCELLED": "cancelled", "PENDING": "pending",
                      "FAILED": "failed", "EXPIRED": "expired"}
        return ParsedNotification(
            our_reference=clean.get("m_payment_id", ""),
            provider_payment_id=clean.get("pf_payment_id", ""),
            status=status_map.get(status, "pending"),
            amount_cents=amount_cents,
            merchant_id=clean.get("merchant_id", ""),
            payment_method=clean.get("payment_method"),
            fields=clean,
        )

    def verify_payment(self, notification: ParsedNotification, source_ip: str) -> VerificationResult:
        supplied = notification.fields.get("signature", "")
        expected = _itn_signature(notification.fields, self.passphrase)
        signature_valid = bool(supplied) and hmac.compare_digest(supplied, expected)
        ip_valid = is_valid_payfast_source_ip(source_ip)
        if not signature_valid:
            return VerificationResult(False, ip_valid, False, "Invalid PayFast ITN signature")
        if not ip_valid:
            return VerificationResult(True, False, False, "ITN source IP is not in PayFast's published ranges")
        try:
            response = httpx.post(self.validate_url, data=dict(notification.fields), timeout=12.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return VerificationResult(True, True, False, f"PayFast confirmation request failed ({type(exc).__name__})")
        confirmed = response.text.strip() == "VALID"
        return VerificationResult(True, True, confirmed,
                                  None if confirmed else "PayFast did not confirm the ITN")

    def refund(self, provider_payment_id: str, amount_cents: int, reason: str) -> RefundResult:
        """Query refundability, then refund card/source payments; never collect bank data here."""
        if not self.merchant_id or not self.passphrase:
            return RefundResult(False, reason="PayFast refund credentials are not configured")
        query_url = f"https://api.payfast.co.za/refunds/query/{provider_payment_id}"
        query_params = {"testing": "true"} if self.api_testing else {}
        headers = self._api_headers()
        try:
            query_response = httpx.get(query_url, params=query_params, headers=headers, timeout=15.0)
            query_response.raise_for_status()
            response_data = query_response.json().get("data", {}).get("response", {})
        except (httpx.HTTPError, ValueError) as exc:
            return RefundResult(False, reason=f"PayFast refund query failed ({type(exc).__name__})")
        if response_data.get("status") != "REFUNDABLE":
            return RefundResult(False, reason="PayFast reports this payment is not refundable")
        methods = response_data.get("refund_full", {})
        if methods.get("method") != "PAYMENT_SOURCE":
            return RefundResult(False, reason="PayFast requires a manual or bank refund for this payment method")
        if amount_cents <= 0 or amount_cents > int(response_data.get("amount_available_for_refund", 0)):
            return RefundResult(False, reason="Refund amount exceeds the PayFast refundable balance")
        body = {"amount": str(amount_cents), "reason": reason[:255],
                "notify_buyer": "1", "notify_merchant": "0"}
        headers = self._api_headers(body)
        try:
            response = httpx.post(
                f"https://api.payfast.co.za/refunds/{provider_payment_id}",
                params=query_params, data=body, headers=headers, timeout=15.0,
            )
            response.raise_for_status()
            data = response.json().get("data", {}).get("response")
        except (httpx.HTTPError, ValueError) as exc:
            return RefundResult(False, reason=f"PayFast refund request failed ({type(exc).__name__})")
        return RefundResult(bool(data), provider_reference=provider_payment_id,
                            reason=None if data else "PayFast did not accept the refund")

    def _api_headers(self, body: Mapping[str, str] | None = None) -> dict[str, str]:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fields = {"merchant-id": self.merchant_id, "version": "v1", "timestamp": stamp}
        fields.update(body or {})
        signature_fields = dict(fields)
        signature_fields["passphrase"] = self.passphrase
        signed = "&".join(f"{key}={_urlencode(str(signature_fields[key]))}"
                          for key in sorted(signature_fields) if signature_fields[key] != "")
        signature = hashlib.md5(signed.encode("utf-8")).hexdigest()
        return {"merchant-id": self.merchant_id, "version": "v1", "timestamp": stamp,
                "signature": signature}


class MockProvider:
    """No-network gateway for local development and automated tests."""

    name = "mock"
    _statuses = {"success", "failure", "pending", "cancelled"}

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        status = os.getenv("MOCK_PAYMENT_RESULT", "success").strip().lower()
        if status not in self._statuses:
            status = "pending"
        return CheckoutResult(
            redirect_url=f"/payments/mock/{request.our_reference}?result={status}",
            fields={"reference": request.our_reference, "amount_cents": str(request.amount_cents)},
            simulated_status=status,
        )

    def parse_notification(self, fields: Mapping[str, str]) -> ParsedNotification:
        try:
            amount_cents = int(fields["amount_cents"])
        except (KeyError, ValueError) as exc:
            raise PaymentProviderError("Mock notification is missing amount_cents") from exc
        status = str(fields.get("status", "pending")).lower()
        if status not in self._statuses:
            status = "pending"
        return ParsedNotification(
            our_reference=str(fields.get("reference", "")),
            provider_payment_id=str(fields.get("payment_id", f"mock-{fields.get('reference', '')}")),
            status={"success": "succeeded", "failure": "failed"}.get(status, status),
            amount_cents=amount_cents,
            merchant_id="mock",
            payment_method=str(fields.get("payment_method", "mock")),
            fields={key: str(value) for key, value in fields.items()},
        )

    def verify_payment(self, notification: ParsedNotification, source_ip: str) -> VerificationResult:
        return VerificationResult(True, True, True)

    def refund(self, provider_payment_id: str, amount_cents: int, reason: str) -> RefundResult:
        return RefundResult(True, provider_reference=f"mock-refund-{provider_payment_id}")


def get_payment_provider(name: str | None = None) -> PaymentProvider:
    selected = (name or os.getenv("PAYMENT_PROVIDER", "mock")).strip().lower()
    if selected == "payfast":
        return PayfastProvider()
    if selected == "mock":
        return MockProvider()
    raise PaymentProviderError("PAYMENT_PROVIDER must be payfast or mock")
