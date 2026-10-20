"""South African tenant phone number validation and E.164 normalization."""

import phonenumbers


def normalize_sa_phone(phone: str) -> str:
    """Normalize a South African number to E.164, or raise a clear ValueError."""
    try:
        parsed = phonenumbers.parse(phone, "ZA")
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Enter a valid South African phone number") from exc
    if not phonenumbers.is_valid_number(parsed) or phonenumbers.region_code_for_number(parsed) != "ZA":
        raise ValueError("Enter a valid South African phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
