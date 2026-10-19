<<<<<<< HEAD
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
=======
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["tenant", "landlord"]
    id_number: str = Field(min_length=13, max_length=13)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("id_number")
    @classmethod
    def validate_id_number(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 13:
            raise ValueError("ID number must contain exactly 13 digits")
        return value


class LoginRequest(BaseModel):
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
    email: str
    password: str


<<<<<<< HEAD
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
=======
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    address: str
    monthly_rent: float
    bedrooms: int


class ApplicationCreate(BaseModel):
    unit_id: int
    consent: bool


class ApplicationResponse(BaseModel):
    id: int
    unit_id: int
    status: str
    credit_score: int
    recommendation: str


class DecisionRequest(BaseModel):
    decision: Literal["approved", "review", "declined"]


class LeaseResponse(BaseModel):
    id: int
    application_id: int
    unit_id: int
    monthly_rent: float
    status: str


class LeaseAcceptanceResponse(BaseModel):
    lease_id: int
    status: str
    rent_charge_id: int


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    message: str
    created_at: datetime
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
