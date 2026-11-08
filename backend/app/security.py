"""Password hashing and signed login tokens, using only the standard library.

Tokens are "<user_id>.<expiry>.<hmac>". A private signing secret from the
environment or backend/.env is required; there is no shared default key.
"""
import hashlib
import hmac
import os
import time
from typing import Optional

ITERATIONS = 120_000
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
SECRET = os.getenv("LANDKEEP_SECRET", "")
if len(SECRET) < 32 or SECRET == "dev-secret-change-me":
    raise RuntimeError("Set LANDKEEP_SECRET to a random secret of at least 32 characters in backend/.env.")
TOKEN_TTL_SECONDS = 8 * 3600


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"{ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    iterations, salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _sign(payload: str) -> str:
    return hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_token(user_id: int) -> str:
    payload = f"{user_id}.{int(time.time()) + TOKEN_TTL_SECONDS}"
    return f"{payload}.{_sign(payload)}"


def decode_token(token: str) -> Optional[int]:
    """Return the user id for a valid, unexpired token, otherwise None."""
    try:
        user_id, expiry, signature = token.split(".")
        if not hmac.compare_digest(_sign(f"{user_id}.{expiry}"), signature):
            return None
        if int(expiry) < time.time():
            return None
        return int(user_id)
    except (ValueError, AttributeError):
        return None
