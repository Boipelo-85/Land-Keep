import re
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
    email: str
    password: str


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
