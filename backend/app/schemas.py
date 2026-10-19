"""Request bodies. Validation lives here so the routes stay short."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=EMAIL_PATTERN)
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=100)


class LoginIn(BaseModel):
    email: str
    password: str


class ApplicationIn(BaseModel):
    unit_id: int
    monthly_income: float = Field(gt=0)
    employer: Optional[str] = Field(default=None, max_length=120)
    id_number: str = Field(pattern=r"^\d{13}$", description="13-digit South African ID number")
    consent_given: bool


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: Optional[str] = Field(default=None, max_length=300)


class ConvertIn(BaseModel):
    start_date: date
    term_months: int = Field(default=12, ge=1, le=36)
    deposit: Optional[float] = Field(default=None, ge=0)  # defaults to one month's rent
    due_day: int = Field(default=1, ge=1, le=28)


class MaintenanceOut(BaseModel):
    id: int
    description: str
    status: str
    created_at: datetime
    has_photo: bool
    unit_number: str
    property: str
