"""Integer-cent money conversions for existing Rand-valued lease and charge fields."""
from decimal import Decimal, ROUND_HALF_UP


def zar_to_cents(amount: int | float | Decimal) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_zar(amount_cents: int) -> Decimal:
    return Decimal(amount_cents) / Decimal(100)
