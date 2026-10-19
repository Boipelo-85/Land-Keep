from datetime import date
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import require_landlord, require_tenant
from ..schemas import AgencyReminderSettingsIn, TenantReminderPreferencesIn
from ..services.agency_reminders import normalize_sa_phone, run_reminders

router = APIRouter(prefix="/reminders", tags=["rent reminders"])


@router.post("/run")
def run_manual(
    dry_run: bool = Query(default=True),
    window_days: int | None = Query(default=None, ge=0, le=31),
    _landlord: m.User = Depends(require_landlord),
    db: Session = Depends(get_db),
):
    """Evaluate this agency's configured window only; never crosses agency boundaries."""
    if window_days is not None and not dry_run:
        raise HTTPException(400, "window_days overrides are available only in dry-run mode")
    return run_reminders(db, agency_id=_landlord.id, dry_run=dry_run, window_days=window_days)


@router.get("/log")
def list_reminder_log(
    landlord: m.User = Depends(require_landlord),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    period: date | None = None,
):
    statement = (
        select(m.AgencyRentReminderLog, m.User, m.Lease, m.Unit, m.Property)
        .join(m.User, m.User.id == m.AgencyRentReminderLog.tenant_id)
        .join(m.Lease, m.Lease.id == m.AgencyRentReminderLog.lease_id)
        .join(m.Unit, m.Unit.id == m.Lease.unit_id)
        .join(m.Property, m.Property.id == m.Unit.property_id)
        .where(m.AgencyRentReminderLog.agency_id == landlord.id,
               m.Property.landlord_id == landlord.id)
        .order_by(m.AgencyRentReminderLog.created_at.desc(), m.AgencyRentReminderLog.id.desc())
        .limit(limit)
    )
    if period is not None:
        statement = statement.where(m.AgencyRentReminderLog.period == period)
    return [
        {
            "id": log.id,
            "tenant_id": tenant.id,
            "tenant": tenant.full_name,
            "lease_id": lease.id,
            "property": prop.name,
            "unit": unit.unit_number,
            "agency_id": log.agency_id,
            "period": log.period,
            "window_days": log.window_days,
            "channel": log.channel,
            "status": log.status,
            "provider_message_id": log.provider_message_id,
            "error": log.error,
            "sent_at": log.sent_at,
            "created_at": log.created_at,
        }
        for log, tenant, lease, unit, prop in db.execute(statement)
    ]


def _settings_out(agency: m.User, row: m.AgencyReminderSettings | None) -> dict:
    windows = row.reminder_windows if row and row.reminder_windows else [
        row.reminder_days_before_month_end if row else 3
    ]
    return {
        "agency_id": agency.id,
        "agency_name": row.agency_name if row and row.agency_name else agency.full_name,
        "contact_email": row.contact_email if row and row.contact_email is not None else agency.email,
        "contact_phone": row.contact_phone if row and row.contact_phone is not None else agency.phone,
        "reminder_days_before_month_end": row.reminder_days_before_month_end if row else 3,
        "reminder_windows": windows,
        "channel_order": row.channel_order if row and row.channel_order else ["whatsapp", "sms", "email"],
        "channel_strategy": row.channel_strategy if row else "fallback",
    }


@router.get("/settings")
def get_settings(agency: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    row = db.scalar(select(m.AgencyReminderSettings).where(
        m.AgencyReminderSettings.agency_id == agency.id
    ))
    return _settings_out(agency, row)


@router.put("/settings")
def update_settings(
    body: AgencyReminderSettingsIn,
    agency: m.User = Depends(require_landlord),
    db: Session = Depends(get_db),
):
    values = body.model_dump(exclude_unset=True)
    row = db.scalar(select(m.AgencyReminderSettings).where(
        m.AgencyReminderSettings.agency_id == agency.id
    ))
    if row is None:
        row = m.AgencyReminderSettings(agency_id=agency.id)
        db.add(row)
    if "reminder_days_before_month_end" in values and "reminder_windows" not in values:
        row.reminder_windows = None
    for key, value in values.items():
        setattr(row, key, value)
    if row.reminder_windows is not None:
        row.reminder_windows = sorted(set(row.reminder_windows), reverse=True)
        if row.reminder_windows:
            row.reminder_days_before_month_end = row.reminder_windows[0]
    db.commit()
    db.refresh(row)
    return _settings_out(agency, row)


@router.get("/preferences")
def get_preferences(tenant: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    row = db.scalar(select(m.TenantChannelPreference).where(
        m.TenantChannelPreference.tenant_id == tenant.id
    ))
    return {
        "whatsapp_opt_in": bool(row and row.whatsapp_opt_in),
        "sms_opt_in": bool(row and row.sms_opt_in),
        "email_opt_in": bool(row and row.email_opt_in),
    }


@router.put("/preferences")
def update_preferences(
    body: TenantReminderPreferencesIn,
    tenant: m.User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(m.TenantChannelPreference).where(
        m.TenantChannelPreference.tenant_id == tenant.id
    ))
    if row is None:
        row = m.TenantChannelPreference(tenant_id=tenant.id)
        db.add(row)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    row.updated_at = m.utcnow()
    db.commit()
    return get_preferences(tenant, db)


@router.post("/twilio/inbound", include_in_schema=False)
async def twilio_inbound(request: Request, db: Session = Depends(get_db)):
    """Apply SMS/WhatsApp STOP opt-outs after validating Twilio's request signature."""
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    signature = request.headers.get("X-Twilio-Signature", "")
    if not auth_token or not signature:
        raise HTTPException(403, "Twilio signature is required")
    form = await request.form()
    external_base = os.getenv("LANDKEEP_PUBLIC_BASE_URL", str(request.base_url).rstrip("/"))
    signed_url = f"{external_base.rstrip('/')}{request.url.path}"
    if request.url.query:
        signed_url += f"?{request.url.query}"
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    if not validator.validate(signed_url, dict(form), signature):
        raise HTTPException(403, "Invalid Twilio signature")

    keyword = str(form.get("Body", "")).strip().upper()
    if keyword in {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
        raw_from = str(form.get("From", "")).replace("whatsapp:", "").strip()
        try:
            normalized_from = normalize_sa_phone(raw_from)
        except ValueError:
            normalized_from = None
        if normalized_from:
            tenant = next((user for user in db.scalars(
                select(m.User).where(m.User.role == "tenant", m.User.phone.is_not(None))
            ) if _safe_normalize(user.phone) == normalized_from), None)
            if tenant is not None:
                pref = db.scalar(select(m.TenantChannelPreference).where(
                    m.TenantChannelPreference.tenant_id == tenant.id
                ))
                if pref is None:
                    pref = m.TenantChannelPreference(tenant_id=tenant.id)
                    db.add(pref)
                if str(form.get("To", "")).startswith("whatsapp:"):
                    pref.whatsapp_opt_in = False
                else:
                    pref.sms_opt_in = False
                pref.updated_at = m.utcnow()
                db.commit()
    return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response/>",
                    media_type="application/xml")


def _safe_normalize(phone: str | None) -> str | None:
    if not phone:
        return None
    try:
        return normalize_sa_phone(phone)
    except ValueError:
        return None
