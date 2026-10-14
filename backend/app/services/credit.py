from app.models import User


def run_credit_check(id_number: str) -> tuple[int, str]:
    """Return a stable demo score; never call this a real credit-bureau result."""
    score = 500 + sum(int(digit) for digit in id_number) % 351
    if score >= 700:
        recommendation = "approved"
    elif score >= 600:
        recommendation = "review"
    else:
        recommendation = "declined"
    return score, recommendation


def recommendation_for(applicant: User) -> tuple[int, str]:
    return run_credit_check(applicant.id_number)
