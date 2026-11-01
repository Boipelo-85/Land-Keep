"""Credit check service.

The rest of the app only talks to `CreditCheckService`. Today it is backed by
`MockCreditBureau` (a deterministic simulation). A real bureau (TransUnion, XDS,
Experian) would be a new class with the same `check` method, so nothing else changes.

The system only RECOMMENDS. The landlord makes the final decision.
"""
import hashlib
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CreditResult:
    score: int
    source: str


class CreditCheckService(Protocol):
    def check(self, id_number: str, monthly_income: float) -> CreditResult: ...


class MockCreditBureau:
    """Simulated score between 300 and 850, repeatable for the same ID number."""

    def check(self, id_number: str, monthly_income: float) -> CreditResult:
        seed = int(hashlib.sha256(id_number.encode()).hexdigest(), 16)
        score = 300 + seed % 551
        if monthly_income >= 25_000:
            score += 30
        elif monthly_income < 10_000:
            score -= 30
        return CreditResult(score=max(300, min(850, score)), source="mock")


# Recommendation thresholds (documented in the report)
APPROVE_MIN_SCORE = 650
DECLINE_MAX_SCORE = 550
MAX_RENT_TO_INCOME = 0.35
HARD_RENT_TO_INCOME = 0.50


def recommend(score: int, monthly_income: float, monthly_rent: float) -> str:
    """Return 'approve', 'review' or 'decline' from score and rent-to-income ratio."""
    ratio = monthly_rent / monthly_income if monthly_income > 0 else 1.0
    if score < DECLINE_MAX_SCORE or ratio > HARD_RENT_TO_INCOME:
        return "decline"
    if score >= APPROVE_MIN_SCORE and ratio <= MAX_RENT_TO_INCOME:
        return "approve"
    return "review"
