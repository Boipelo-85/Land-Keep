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

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TenantChannelPreference(Base):
    """Per-tenant opt-in consent for automated rent reminders."""

    __tablename__ = "tenant_channel_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AgencyReminderSettings(Base):
    """Reminder schedule and channel policy for a landlord/agency account."""

    __tablename__ = "agency_reminder_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    reminder_days_before_month_end: Mapped[int] = mapped_column(Integer, default=3)
    reminder_windows: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    channel_order: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["whatsapp", "sms", "email"])
    channel_strategy: Mapped[str] = mapped_column(String(20), default="fallback")
    agency_name: Mapped[Optional[str]] = mapped_column(String(160))
    contact_email: Mapped[Optional[str]] = mapped_column(String(160))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    landlord_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    units: Mapped[list["Unit"]] = relationship(back_populates="property")


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
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


class Lease(Base):
    __tablename__ = "leases"

    id: Mapped[int] = mapped_column(primary_key=True)
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


class RentCharge(Base):
    __tablename__ = "rent_charges"

    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), index=True)
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


class RentReminderLog(Base):
    """Idempotency and delivery record for month-end rent reminders."""

    __tablename__ = "rent_reminder_logs"
    __table_args__ = (UniqueConstraint("lease_id", "period", "window_days",
                                       name="uq_rent_reminder_lease_period_window"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), index=True)
    period: Mapped[date] = mapped_column(Date, index=True)
    window_days: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(20), default="console")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgencyRentReminderLog(Base):
    """Per-channel attempt log; uniqueness prevents cross-run duplicate delivery."""

    __tablename__ = "agency_rent_reminder_logs"
    __table_args__ = (UniqueConstraint(
        "lease_id", "period", "window_days", "channel",
        name="uq_agency_rent_reminder_lease_period_window_channel",
    ),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), index=True)
    period: Mapped[date] = mapped_column(Date, index=True)
    window_days: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))  # sent, failed, skipped
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(120))
    error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """Every email/SMS the system sends, whatever the provider (console, SMTP, Twilio)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # email, sms (whatsapp later)
    template: Mapped[str] = mapped_column(String(60))
    subject: Mapped[Optional[str]] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
