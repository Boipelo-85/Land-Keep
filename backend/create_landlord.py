"""Create a landlord account from an administrative backend terminal."""
import argparse
from getpass import getpass

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import User
from app.security import hash_password, is_fixture_account


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    email, name = args.email.strip().lower(), args.name.strip()
    local, separator, domain = email.partition("@")
    if (not separator or not local or "." not in domain or "@" in domain
            or any(char.isspace() for char in email) or len(email) > 160 or is_fixture_account(email)):
        parser.error("Provide a valid landlord email address")
    if not name or len(name) > 120:
        parser.error("Provide a name between 1 and 120 characters")
    password = getpass("Landlord password (at least 12 characters): ")
    if len(password) < 12 or password != getpass("Confirm password: "):
        parser.error("Passwords must match and be at least 12 characters")
    with SessionLocal() as db:
        db.add(User(role="landlord", full_name=name, email=email, password_hash=hash_password(password)))
        try:
            db.commit()
        except IntegrityError:
            parser.exit(1, "Could not create the account. Check whether the email is already in use.\n")
    print(f"Created landlord {email}")


if __name__ == "__main__":
    main()
