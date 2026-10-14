import base64
import hashlib
import hmac
import json
import os
import secrets
import time

SECRET_KEY = os.getenv("LANDKEEP_SECRET_KEY", "local-development-key-change-me")
TOKEN_TTL_SECONDS = 60 * 60 * 12


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt_text, digest_text = password_hash.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: int) -> str:
    payload = json.dumps(
        {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
        separators=(",", ":"),
    ).encode()
    encoded_payload = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(SECRET_KEY.encode(), encoded_payload, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{encoded_payload.decode()}.{encoded_signature.decode()}"


def decode_access_token(token: str) -> int:
    try:
        encoded_payload, encoded_signature = token.encode().split(b".", 1)
        expected = hmac.new(SECRET_KEY.encode(), encoded_payload, hashlib.sha256).digest()
        signature = base64.urlsafe_b64decode(encoded_signature + b"=" * (-len(encoded_signature) % 4))
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid token signature")
        payload_bytes = base64.urlsafe_b64decode(encoded_payload + b"=" * (-len(encoded_payload) % 4))
        payload = json.loads(payload_bytes)
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("Token expired")
        return int(payload["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired access token") from exc
