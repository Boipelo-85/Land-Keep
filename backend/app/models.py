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

from sqlalchemy import Index, func, Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, text
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
CHAT_MAINTENANCE_CATEGORIES = (
    "plumbing", "electrical", "appliance", "roof_damp", "doors_locks", "pests", "other"
)
CHAT_MAINTENANCE_URGENCIES = ("low", "medium", "high", "emergency")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    # Automated rent reminder consent belongs to the tenant record.
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    consent_recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
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
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminder_days_before_month_end: Mapped[int] = mapped_column(Integer, default=3)
    reminder_windows: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    channel_order: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["whatsapp", "sms", "email"])
    enabled_channels: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["whatsapp", "sms", "email"], nullable=False
    )
    channel_strategy: Mapped[str] = mapped_column(String(20), default="all")
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

    __table_args__ = (Index("uq_unit_property_number", property_id, func.lower(unit_number), unique=True),)

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
    __table_args__ = (UniqueConstraint("lease_id", "period", name="uq_rent_charge_lease_period"),)

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
    amount_cents: Mapped[int] = mapped_column(Integer)
    paid_at: Mapped[datetime] = mapped_column(DateTime)
    method: Mapped[str] = mapped_column(String(20))  # eft, debit_order, cash
    provider: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(100))
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    gateway_attempt_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payment_attempts.id"), unique=True, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaymentAttempt(Base):
    """A tenant-initiated provider checkout; only a verified notification settles it."""

    __tablename__ = "payment_attempts"
    __table_args__ = (Index("uq_paystack_open_charge", "rent_record_id", unique=True,
        sqlite_where=text("provider = 'paystack' AND status IN ('initiated', 'pending')"),
        postgresql_where=text("provider = 'paystack' AND status IN ('initiated', 'pending')")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), index=True)
    rent_record_id: Mapped[int] = mapped_column(ForeignKey("rent_charges.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    platform_fee_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ZAR", nullable=False)
    provider: Mapped[str] = mapped_column(String(20), default="payfast", nullable=False)
    our_reference: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    # Legacy checkout columns remain mapped during the transition so existing
    # installations can migrate without discarding their audit history.
    payment_reference: Mapped[str] = mapped_column(String(80), unique=True)
    charge_id: Mapped[int] = mapped_column(ForeignKey("rent_charges.id"), index=True)
    checkout_url: Mapped[Optional[str]] = mapped_column(Text)
    recipient_merchant_id: Mapped[str] = mapped_column(String(8))
    provider_transaction_id: Mapped[Optional[str]] = mapped_column(String(100))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="initiated", index=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    payment_method: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class PaymentNotificationLog(Base):
    """Idempotency key and non-sensitive result of each provider callback."""

    __tablename__ = "payment_notification_logs"
    __table_args__ = (UniqueConstraint("provider", "provider_payment_id", "status",
                                       name="uq_payment_notification_provider_payment_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)
    provider_payment_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ip_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    server_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(300))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgencyPaymentSettings(Base):
    """Payment policy and PayFast destination for one landlord/agency."""

    __tablename__ = "agency_payment_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    payments_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payfast_merchant_id: Mapped[Optional[str]] = mapped_column(String(8))
    verification_status: Mapped[str] = mapped_column(String(20), default="not_verified", nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    verified_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    who_pays_fees: Mapped[str] = mapped_column(String(10), default="landlord", nullable=False)
    platform_fee_type: Mapped[str] = mapped_column(String(12), default="fixed", nullable=False)
    platform_fee_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    platform_fee_basis_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    allow_partial_payments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    minimum_partial_amount_cents: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AgencyPaymentSettingsAudit(Base):
    """Audit only masked merchant IDs; never copy merchant secrets into the audit trail."""

    __tablename__ = "agency_payment_settings_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    old_merchant_id_masked: Mapped[Optional[str]] = mapped_column(String(12))
    new_merchant_id_masked: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class MerchantVerificationAttempt(Base):
    """Small PayFast split checkout used to verify an agency recipient account."""

    __tablename__ = "merchant_verification_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    our_reference: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="initiated", index=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class LandlordPaymentSettings(Base):
    """PayFast recipient details for one landlord; never sourced from platform env."""

    __tablename__ = "landlord_payment_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    landlord_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    payfast_merchant_id: Mapped[str] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    photo_path: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    ai_category: Mapped[Optional[str]] = mapped_column(String(30))
    ai_urgency: Mapped[Optional[str]] = mapped_column(String(20))
    ai_summary: Mapped[Optional[str]] = mapped_column(String(500))
    ai_likely_cause: Mapped[Optional[str]] = mapped_column(String(500))
    tried_self_help: Mapped[Optional[str]] = mapped_column(Text)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("maintenance_conversations.id"), unique=True
    )
    # ML fields: what the model suggested vs what the landlord confirmed.
    # Comparing the two columns over time measures real-world model accuracy.
    classification_model_version: Mapped[Optional[str]] = mapped_column(String(80))
    classification_priority_score: Mapped[Optional[float]] = mapped_column(Float)
    classification_score: Mapped[Optional[float]] = mapped_column(Float)
    predicted_category: Mapped[Optional[str]] = mapped_column(String(20))
    predicted_urgency: Mapped[Optional[str]] = mapped_column(String(10))
    confirmed_category: Mapped[Optional[str]] = mapped_column(String(20))
    confirmed_urgency: Mapped[Optional[str]] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class MaintenanceConversation(Base):
    """Private, agency-scoped tenant chat that can produce a maintenance request."""

    __tablename__ = "maintenance_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("leases.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    photo_sharing_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    photo_sharing_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    photo_sharing_notice_version: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class MaintenanceMessage(Base):
    __tablename__ = "maintenance_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # tenant, bot
    text: Mapped[str] = mapped_column(Text)
    flagged_emergency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class MaintenanceAttachment(Base):
    __tablename__ = "maintenance_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_messages.id", ondelete="CASCADE"), index=True
    )
    storage_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
    """Per-channel attempt log; uniqueness prevents cross-run duplicate delivery.

    ``period`` is the first day of the billing month (the existing representation
    of YYYY-MM); ``window_days`` records the month-end reminder window.
    """

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
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/sent/delivered/failed/skipped
    skip_reason: Mapped[Optional[str]] = mapped_column(String(200))
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(120))
    error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
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



class AutomationMessage(Base):
    __tablename__ = "automation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[Optional[int]] = mapped_column(ForeignKey("maintenance_requests.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(10))
    mode: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[Optional[str]] = mapped_column(String(300))
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(180), unique=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Contractor(Base):
    __tablename__ = 'contractors'
    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    trade: Mapped[str] = mapped_column(String(30))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MaintenanceWorkOrder(Base):
    __tablename__ = 'maintenance_work_orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey('maintenance_requests.id'), index=True)
    contractor_id: Mapped[int] = mapped_column(ForeignKey('contractors.id'))
    agency_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(30), default='assigned')
    scheduled_for: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaystackSettings(Base):
    """Per-landlord opt-in; all receipts settle to the platform Paystack account."""
    __tablename__ = "paystack_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    payments_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
