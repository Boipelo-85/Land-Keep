"""Paystack hosted checkout. Secret credentials and all verification stay on the server."""
import hashlib
import hmac
import os
import re
import time
from urllib.parse import quote, urlparse

import httpx
from .payment_providers import PaymentProviderError


class PaystackRejected(PaymentProviderError):
    """A definite rejection before checkout; unlike a timeout, safe to retry."""


def secret_key():
    key = os.getenv('PAYSTACK_SECRET_KEY', '').strip()
    if not key.startswith(('sk_test_', 'sk_live_')):
        raise PaymentProviderError('Online payments have not been configured. Contact the platform administrator.')
    return key


def mode():
    return 'live' if os.getenv('PAYSTACK_SECRET_KEY', '').strip().startswith('sk_live_') else 'test'


def request(method, path, payload=None):
    try:
        response = httpx.request(method, 'https://api.paystack.co' + path,
            headers={'Authorization': f'Bearer {secret_key()}'}, json=payload, timeout=15)
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise PaystackRejected('Paystack rejected the request. Check the account configuration and try again.')
        response.raise_for_status()
        result = response.json()
        if result.get('status') is not True or not isinstance(result.get('data'), dict):
            raise PaystackRejected('Paystack could not complete this request. Check the account configuration.')
        return result['data']
    except (httpx.HTTPError, ValueError) as exc:
        raise PaymentProviderError('Paystack is temporarily unavailable. Check the payment status before trying again.') from exc


def initialize(reference, amount_cents, email):
    callback = os.getenv('PAYSTACK_CALLBACK_URL', '').strip() or 'http://localhost:5173/pay-rent?payment=return'
    parsed = urlparse(callback)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or (mode() == 'live' and parsed.scheme != 'https'):
        raise PaymentProviderError('Configure a valid PAYSTACK_CALLBACK_URL; live payments require HTTPS.')
    data = request('POST', '/transaction/initialize', {
        'email': email, 'amount': amount_cents, 'currency': 'ZAR',
        'reference': reference, 'callback_url': callback,
        'metadata': {'purpose': 'LandKeep rent'},
    })
    destination = urlparse(data.get('authorization_url', ''))
    if destination.scheme != 'https' or destination.hostname != 'checkout.paystack.com' or destination.username or destination.password:
        raise PaymentProviderError('Paystack returned an invalid checkout destination.')
    if data.get('reference') != reference:
        raise PaymentProviderError('Paystack returned an unexpected payment reference.')
    return data['authorization_url']


def verify(reference):
    return request('GET', '/transaction/verify/' + quote(reference, safe=''))


def valid_signature(body, headers):
    modern = headers.get('paystack-signature')
    signing_key = os.getenv('PAYSTACK_WEBHOOK_SECRET', '').strip()
    if modern:
        if not signing_key:
            return False
        timestamp = None
        signatures = []
        for item in modern.split(','):
            key, _, value = item.strip().partition('=')
            if key == 't':
                if timestamp is not None or not value.isdigit():
                    return False
                timestamp = value
            elif key == 'v1':
                _, sep, signature = value.partition(':')
                if sep and re.fullmatch('[0-9a-f]{128}', signature):
                    signatures.append(signature)
        if timestamp is None or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(signing_key.encode(), timestamp.encode() + b'.' + body, hashlib.sha512).hexdigest()
        return any(hmac.compare_digest(expected, signature) for signature in signatures)
    # Once a signing secret is configured, do not permit downgrade to the old header.
    if signing_key:
        return False
    legacy = headers.get('x-paystack-signature', '')
    if not re.fullmatch('[0-9a-f]{128}', legacy):
        return False
    expected = hmac.new(secret_key().encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, legacy)
