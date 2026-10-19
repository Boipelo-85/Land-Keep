<<<<<<< HEAD
"""LandKeep data model.

Design rules:
- Every table has created_at, and every business event has its own timestamp
  (rent due/paid, request opened/resolved, application decided). The analytics
  and the future late-payment prediction are built on these.
- An applicant and a tenant are the SAME User row at different stages. The
  application status pipeline plus ApplicationStatusHistory is the tracking system.
- Money is stored as float for the university prototype. Use Numeric/Decimal
  (or integer cents) in production.
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Allowed values (kept as plain strings so SQLite and PostgreSQL behave the same)
ROLES = ("landlord", "tenant")
UNIT_STATUSES = ("vacant", "occupied")
APPLICATION_STATUSES = ("submitted", "under_review", "approved", "rejected", "lease_issued", "active_tenant")
MAINTENANCE_STATUSES = ("open", "in_progress", "resolved")
CATEGORIES = ("plumbing", "electrical", "security", "general")
URGENCIES = ("high", "low")
=======
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
<<<<<<< HEAD
    role: Mapped[str] = mapped_column(String(20), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    landlord_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    units: Mapped[list["Unit"]] = relationship(back_populates="property")
=======
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    id_number: Mapped[str] = mapped_column(String(13), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
<<<<<<< HEAD
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    unit_number: Mapped[str] = mapped_column(String(20))
    bedrooms: Mapped[int] = mapped_column(Integer)
    monthly_rent: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="vacant", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    property: Mapped["Property"] = relationship(back_populates="units")


class TenantApplication(Base):
    __tablename__ = "tenant_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    monthly_income: Mapped[float] = mapped_column(Float)
    employer: Mapped[Optional[str]] = mapped_column(String(120))
    id_number: Mapped[str] = mapped_column(String(20))
    # POPIA: a credit check needs the applicant's recorded consent
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    credit_score: Mapped[Optional[int]] = mapped_column(Integer)
    credit_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    recommendation: Mapped[Optional[str]] = mapped_column(String(20))  # approve / review / decline
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    decision_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    history: Mapped[list["ApplicationStatusHistory"]] = relationship(
        back_populates="application", order_by="ApplicationStatusHistory.created_at"
    )


class ApplicationStatusHistory(Base):
    """One row per status change. This is the application tracking timeline."""

    __tablename__ = "application_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("tenant_applications.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[Optional[str]] = mapped_column(String(300))
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped["TenantApplication"] = relationship(back_populates="history")
=======
    landlord_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    address: Mapped[str] = mapped_column(String(255))
    monthly_rent: Mapped[float] = mapped_column(Numeric(10, 2))
    bedrooms: Mapped[int] = mapped_column(Integer, default=1)
    is_vacant: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CreditCheck(Base):
    __tablename__ = "credit_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), unique=True)
    score: Mapped[int] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(20))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3


class Lease(Base):
    __tablename__ = "leases"

    id: Mapped[int] = mapped_column(primary_key=True)
<<<<<<< HEAD
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    application_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenant_applications.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    monthly_rent: Mapped[float] = mapped_column(Float)
    deposit: Mapped[float] = mapped_column(Float)
    due_day: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, active, ended
    pdf_path: Mapped[Optional[str]] = mapped_column(String(255))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # tenant accepted the lease
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
=======
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), unique=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    monthly_rent: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), default="pending_acceptance")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LeaseAcceptance(Base):
    __tablename__ = "lease_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), unique=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3


class RentCharge(Base):
    __tablename__ = "rent_charges"

    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), index=True)
<<<<<<< HEAD
    period: Mapped[date] = mapped_column(Date)  # first day of the billing month
    amount_due: Mapped[float] = mapped_column(Float)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    charge_id: Mapped[int] = mapped_column(ForeignKey("rent_charges.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    paid_at: Mapped[datetime] = mapped_column(DateTime)
    method: Mapped[str] = mapped_column(String(20))  # eft, debit_order, cash
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    photo_path: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # ML fields: what the model suggested vs what the landlord confirmed.
    # Comparing the two columns over time measures real-world model accuracy.
    predicted_category: Mapped[Optional[str]] = mapped_column(String(20))
    predicted_urgency: Mapped[Optional[str]] = mapped_column(String(10))
    confirmed_category: Mapped[Optional[str]] = mapped_column(String(20))
    confirmed_urgency: Mapped[Optional[str]] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ReminderLog(Base):
    """Every automated rent reminder that was sent (automation audit trail)."""

    __tablename__ = "reminder_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    charge_id: Mapped[int] = mapped_column(ForeignKey("rent_charges.id"), index=True)
    step: Mapped[int] = mapped_column(Integer)  # days overdue that triggered it: 1, 5, 10
    channel: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """Every email/SMS the system sends, whatever the provider (console, SMTP, Twilio)."""

=======
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    due_date: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="due")


class Notification(Base):
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
<<<<<<< HEAD
    channel: Mapped[str] = mapped_column(String(20))  # email, sms (whatsapp later)
    template: Mapped[str] = mapped_column(String(60))
    subject: Mapped[Optional[str]] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
=======
    channel: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
