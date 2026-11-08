"""Provision a private local signing key once; never print it or replace a valid key."""
import os
from pathlib import Path
import secrets
from dotenv import dotenv_values, set_key


def ensure_secret():
    path = Path(__file__).resolve().parent / ".env"
    value = os.getenv("LANDKEEP_SECRET") or dotenv_values(path).get("LANDKEEP_SECRET")
    if value:
        if len(value) < 32 or value == "dev-secret-change-me":
            raise RuntimeError("Replace LANDKEEP_SECRET with a random value of at least 32 characters in backend/.env.")
        return
    path.touch(exist_ok=True)
    set_key(path, "LANDKEEP_SECRET", secrets.token_urlsafe(48))
    print("Created a private login signing key in backend/.env.")


if __name__ == "__main__":
    ensure_secret()
