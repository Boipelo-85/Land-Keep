"""Tenant maintenance reports: describe a problem, optionally attach a photo."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import BASE_DIR, get_db
from ..deps import get_current_user, require_landlord, require_tenant
from ..schemas import MaintenanceOut
from ..services.notifications import send_notification
from ..services import maintenance_chat as chat
from ..services.maintenance_storage import NOTICE_VERSION, read_private_attachment, store_maintenance_photo
from ..services.reminder_senders import build_sender, send_with_retries
from ..security import SECRET

router = APIRouter(tags=["maintenance"])

PHOTO_DIR = BASE_DIR / "storage" / "maintenance"
MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
EXT_FALLBACK = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}


def _conversation_access(db: Session, conversation_id: int, user: m.User) -> m.MaintenanceConversation:
    row = db.get(m.MaintenanceConversation, conversation_id)
    if row is None or (user.role == "tenant" and row.tenant_id != user.id) or (user.role == "landlord" and row.agency_id != user.id):
        raise HTTPException(404, "Conversation not found")
    return row


def _notify_landlord(db: Session, conversation: m.MaintenanceConversation, subject: str, body: str, urgent: bool) -> None:
    """Urgent notifications reuse the rent-reminder sender adapters; failures never erase a request."""
    settings = db.scalar(select(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == conversation.agency_id))
    agency = db.get(m.User, conversation.agency_id)
    channels = (settings.enabled_channels if settings else ["email", "sms"])
    for channel in channels:
        if channel not in {"email", "sms", "whatsapp"}:
            continue
        recipient = ((settings.contact_email if settings else None) or agency.email) if channel == "email" else ((settings.contact_phone if settings else None) or agency.phone)
        # Console sender still records an actionable notification when no contact is configured.
        if not recipient and os.getenv("LANDKEEP_REMINDER_CONSOLE", "true").lower() not in {"1", "true", "yes"}:
            continue
        try:
            send_with_retries(build_sender(channel), recipient or f"agency:{conversation.agency_id}", subject, body)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Maintenance notification failed for agency %s", conversation.agency_id)
        if settings and settings.channel_strategy == "fallback":
            break


def _create_request(db: Session, conversation: m.MaintenanceConversation, analysis: chat.Analysis, answer: str = "") -> m.MaintenanceRequest:
    existing = db.scalar(select(m.MaintenanceRequest).where(m.MaintenanceRequest.conversation_id == conversation.id))
    if existing:
        return existing
    messages = db.scalars(select(m.MaintenanceMessage).where(m.MaintenanceMessage.conversation_id == conversation.id).order_by(m.MaintenanceMessage.created_at)).all()
    suggested = "\n".join(f"{x.role}: {x.text}" for x in messages if x.role == "bot")
    tenant = db.get(m.User, conversation.tenant_id)
    unit = db.get(m.Unit, conversation.unit_id)
    prop = db.get(m.Property, unit.property_id)
    req = m.MaintenanceRequest(unit_id=conversation.unit_id, tenant_id=conversation.tenant_id,
        description=analysis.summary or "Maintenance issue reported through chat", status="open", source="chatbot",
        ai_category=analysis.category, ai_urgency=analysis.urgency, ai_summary=analysis.summary,
        ai_likely_cause=analysis.likely_cause, tried_self_help=(suggested + (f"\nTenant response: {answer}" if answer else "")), conversation_id=conversation.id)
    db.add(req)
    conversation.status = "escalated"
    db.flush()
    db.add(m.MaintenanceMessage(conversation_id=conversation.id, role="bot", text=f"Your report reference is MR-{req.id:06d}. Your landlord has been notified. {chat.DISCLAIMER}"))
    db.flush()
    if analysis.urgency in {"high", "emergency"}:
        _notify_landlord(db, conversation, f"URGENT: Maintenance report MR-{req.id:06d}",
            f"Tenant: {tenant.full_name}\nProperty/unit: {prop.name}, {unit.unit_number}\nUrgency: {analysis.urgency}\nSummary: {analysis.summary}\nCause: {analysis.likely_cause}\nDetails: {suggested}\nTenant response: {answer or 'Not provided'}\nView in LandKeep.", True)
    return req


def _conversation_out(db: Session, row: m.MaintenanceConversation, user: m.User) -> dict:
    messages = db.scalars(select(m.MaintenanceMessage).where(m.MaintenanceMessage.conversation_id == row.id).order_by(m.MaintenanceMessage.created_at)).all()
    out = []
    for item in messages:
        attachments = db.scalars(select(m.MaintenanceAttachment).where(m.MaintenanceAttachment.message_id == item.id)).all()
        out.append({"id": item.id, "role": item.role, "text": item.text, "created_at": item.created_at,
                    "flagged_emergency": item.flagged_emergency,
                    "attachments": [{"id": a.id, "content_type": a.content_type, "size": a.size,
                                     "url": f"/api/maintenance/attachments/{a.id}/link"} for a in attachments]})
    req = db.scalar(select(m.MaintenanceRequest).where(m.MaintenanceRequest.conversation_id == row.id))
    return {"id": row.id, "status": row.status, "agency_id": row.agency_id, "tenant_id": row.tenant_id,
            "messages": out, "request_id": req.id if req else None,
            "is_tenant": user.role == "tenant"}


def _attachment_token(attachment_id: int, expiry: int) -> str:
    payload = f"{attachment_id}.{expiry}"
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _active_lease(db: Session, user: m.User) -> m.Lease | None:
    return db.scalar(
        select(m.Lease)
        .where(m.Lease.tenant_id == user.id, m.Lease.status == "active")
        .order_by(m.Lease.created_at.desc())
    )


def _request_out(db: Session, req: m.MaintenanceRequest) -> dict:
    unit = db.get(m.Unit, req.unit_id)
    prop = db.get(m.Property, unit.property_id)
    return MaintenanceOut(
        id=req.id,
        description=req.description,
        status=req.status,
        created_at=req.created_at,
        has_photo=bool(req.photo_path),
        unit_number=unit.unit_number,
        property=prop.name,
    ).model_dump()


def _photo_ext(photo: UploadFile) -> str:
    content_type = (photo.content_type or "").lower().split(";")[0].strip()
    if content_type in ALLOWED_TYPES:
        return ALLOWED_TYPES[content_type]
    name = (photo.filename or "").lower()
    for ext, mapped in EXT_FALLBACK.items():
        if name.endswith(ext):
            return mapped
    raise HTTPException(400, "Photo must be a jpg, png, or webp file")


@router.post("/maintenance", status_code=201)
async def report_problem(
    description: str = Form(..., min_length=5, max_length=1000),
    photo: UploadFile | None = File(None),
    user: m.User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    lease = _active_lease(db, user)
    if lease is None:
        raise HTTPException(400, "You need an active lease to report a problem")

    description = description.strip()
    if len(description) < 5:
        raise HTTPException(400, "Description must be at least 5 characters")

    req = m.MaintenanceRequest(
        unit_id=lease.unit_id,
        tenant_id=user.id,
        description=description,
        status="open",
    )
    db.add(req)
    db.flush()

    if photo is not None and photo.filename:
        ext = _photo_ext(photo)
        data = await photo.read()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(400, "Photo must be 5 MB or smaller")
        if not data:
            raise HTTPException(400, "Photo file is empty")
        PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        relative = f"storage/maintenance/{req.id}{ext}"
        (BASE_DIR / relative).write_bytes(data)
        req.photo_path = relative

    unit = db.get(m.Unit, lease.unit_id)
    summary = description if len(description) <= 80 else description[:77] + "..."
    send_notification(db, user, "maintenance_received", unit=unit.unit_number, summary=summary)
    db.commit()
    db.refresh(req)
    return _request_out(db, req)


@router.get("/maintenance/mine")
def my_requests(user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(m.MaintenanceRequest)
        .where(m.MaintenanceRequest.tenant_id == user.id)
        .order_by(m.MaintenanceRequest.created_at.desc())
    ).all()
    return [_request_out(db, r) for r in rows]


@router.get("/maintenance/{request_id}/photo")
def request_photo(
    request_id: int,
    user: m.User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    req = db.get(m.MaintenanceRequest, request_id)
    if req is None or req.tenant_id != user.id or not req.photo_path:
        raise HTTPException(404, "Photo not found")
    path = BASE_DIR / req.photo_path
    if not path.exists():
        raise HTTPException(404, "Photo not found")
    media = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return FileResponse(path, media_type=media.get(path.suffix.lower(), "application/octet-stream"))


@router.post("/maintenance/conversations", status_code=201)
def start_conversation(body: dict, user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    lease_id = body.get("lease_id")
    statement = select(m.Lease).where(m.Lease.tenant_id == user.id, m.Lease.status == "active")
    if lease_id is not None:
        statement = statement.where(m.Lease.id == lease_id)
    lease = db.scalar(statement.order_by(m.Lease.created_at.desc()))
    if lease is None:
        raise HTTPException(400, "You need an active lease to start a maintenance chat")
    unit = db.get(m.Unit, lease.unit_id)
    prop = db.get(m.Property, unit.property_id)
    consent = bool(body.get("photo_sharing_consent", False))
    row = m.MaintenanceConversation(agency_id=prop.landlord_id, tenant_id=user.id, lease_id=lease.id,
        unit_id=unit.id, photo_sharing_consent=consent,
        photo_sharing_consent_at=m.utcnow() if consent else None,
        photo_sharing_notice_version=NOTICE_VERSION if consent else None)
    db.add(row)
    db.flush()
    db.add(m.MaintenanceMessage(conversation_id=row.id, role="bot", text=f"Hi {user.full_name.split()[0]}, tell me what is wrong. You can attach photos. Photos you upload are shared privately with your landlord and Anthropic's AI service for this assessment. {chat.DISCLAIMER}"))
    db.commit()
    return _conversation_out(db, row, user)


@router.post("/maintenance/conversations/{conversation_id}/messages")
async def conversation_message(conversation_id: int, text: str = Form(""), photos: list[UploadFile] = File(default=[]),
                              user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    row = _conversation_access(db, conversation_id, user)
    if row.status != "open":
        raise HTTPException(409, "This conversation is no longer open")
    text = text.strip()
    if len(text) > 2000 or (not text and not photos):
        raise HTTPException(400, "Add a message (up to 2000 characters) or a photo")
    try:
        chat.within_limits(db, user.id, row.id)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    max_photos = int(os.getenv("MAINTENANCE_MAX_PHOTOS_PER_CONVERSATION", "5"))
    photo_count = db.scalar(select(func.count(m.MaintenanceAttachment.id)).join(m.MaintenanceMessage).where(m.MaintenanceMessage.conversation_id == row.id)) or 0
    if photo_count + len(photos) > max_photos:
        raise HTTPException(400, f"You can attach up to {max_photos} photos per chat")
    if photos and not row.photo_sharing_consent:
        raise HTTPException(400, "Please accept the photo sharing notice before uploading photos")
    incoming = m.MaintenanceMessage(conversation_id=row.id, role="tenant", text=text or "[Photo attached]")
    db.add(incoming)
    db.flush()
    paths = []
    for upload in photos:
        raw = await upload.read(5 * 1024 * 1024 + 1)
        try:
            stored = store_maintenance_photo(raw)
        except ValueError as exc:
            db.rollback()
            for path in paths:
                try: (BASE_DIR / path).unlink(missing_ok=True)
                except OSError: pass
            raise HTTPException(400, str(exc)) from exc
        paths.append(stored.storage_path)
        db.add(m.MaintenanceAttachment(message_id=incoming.id, storage_path=stored.storage_path, content_type=stored.content_type, size=stored.size))
    trigger = chat.detect_emergency(text)
    landlord_requested = not trigger and chat.wants_landlord(text)
    incoming.flagged_emergency = bool(trigger)
    db.flush()
    try:
        if trigger:
            result = chat.Analysis(reply=chat.emergency_reply(trigger), category="other", urgency="emergency", summary=f"Potential {trigger} emergency", likely_cause="Requires urgent human assessment", confidence=1, diy_appropriate=False)
            db.add(m.MaintenanceMessage(conversation_id=row.id, role="bot", text=result.reply, flagged_emergency=True))
            db.flush()
            _create_request(db, row, result)
        elif landlord_requested:
            result = chat.Analysis(reply="", category="other", urgency="medium", summary=text[:500] or "Tenant requested landlord assistance", likely_cause="Tenant requested human assistance", confidence=1, diy_appropriate=False)
            db.add(m.MaintenanceMessage(conversation_id=row.id, role="bot", text="I have sent this to your landlord for review."))
            db.flush()
            _create_request(db, row, result, "Tenant asked to report this during chat")
        else:
            try:
                history = db.scalars(select(m.MaintenanceMessage).where(
                    m.MaintenanceMessage.conversation_id == row.id).order_by(m.MaintenanceMessage.created_at.desc()).limit(8)).all()
                transcript = "\n".join(f"{item.role}: {item.text}" for item in reversed(history))
                result = chat.analyze_with_claude(transcript or text or "Please assess the attached maintenance photo.", paths)
                result = chat.validate_analysis(result.model_dump())
            except Exception:
                result = chat.fallback_analysis()
            db.add(m.MaintenanceMessage(conversation_id=row.id, role="bot", text=result.reply))
            db.flush()
            if result.category == "other" and result.confidence == 0:
                _create_request(db, row, result)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _conversation_out(db, row, user)


@router.post("/maintenance/conversations/{conversation_id}/resolve")
def resolve_or_escalate(conversation_id: int, body: dict, user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    row = _conversation_access(db, conversation_id, user)
    solved = bool(body.get("solved", False))
    answer = "Yes, it solved the problem." if solved else str(body.get("answer") or "No or unsure")[:500]
    db.add(m.MaintenanceMessage(conversation_id=row.id, role="tenant", text=f"Did that solve it? {answer}"))
    if solved:
        row.status = "resolved_self_help"
        row.closed_at = m.utcnow()
        db.add(m.MaintenanceMessage(conversation_id=row.id, role="bot", text=f"Glad it is resolved. This chat is closed. {chat.DISCLAIMER}"))
    else:
        result = chat.Analysis(reply="", category="other", urgency="medium", summary="Tenant reports maintenance problem remains unresolved", likely_cause="Needs landlord assessment", confidence=0, diy_appropriate=False)
        _create_request(db, row, result, answer)
    db.commit()
    return _conversation_out(db, row, user)


@router.post("/maintenance/conversations/{conversation_id}/escalate")
def escalate_conversation(conversation_id: int, user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    row = _conversation_access(db, conversation_id, user)
    result = chat.Analysis(reply="", category="other", urgency="medium", summary="Tenant requested landlord assistance", likely_cause="Needs landlord assessment", confidence=0, diy_appropriate=False)
    _create_request(db, row, result, "Tenant asked to report this to the landlord")
    db.commit()
    return _conversation_out(db, row, user)


@router.get("/maintenance/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _conversation_access(db, conversation_id, user)
    return _conversation_out(db, row, user)


@router.get("/maintenance/attachments/{attachment_id}/link")
def attachment_link(attachment_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    attachment = db.get(m.MaintenanceAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "Attachment not found")
    message = db.get(m.MaintenanceMessage, attachment.message_id)
    conversation = _conversation_access(db, message.conversation_id, user)
    expiry = int(datetime.now(timezone.utc).timestamp()) + 300
    token = _attachment_token(attachment.id, expiry)
    return {"url": f"/api/maintenance/attachments/{attachment.id}?token={quote(token)}", "expires_at": expiry}


@router.get("/maintenance/attachments/{attachment_id}")
def attachment_file(attachment_id: int, token: str, db: Session = Depends(get_db)):
    try:
        raw_id, raw_expiry, signature = token.split(".")
        payload = f"{raw_id}.{raw_expiry}"
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        valid = int(raw_id) == attachment_id and int(raw_expiry) >= int(datetime.now(timezone.utc).timestamp()) and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, "Link expired or invalid")
    attachment = db.get(m.MaintenanceAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(404, "Attachment not found")
    try:
        data = read_private_attachment(attachment.storage_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Attachment not found") from exc
    from fastapi.responses import Response
    return Response(data, media_type=attachment.content_type, headers={"Cache-Control": "private, no-store"})


@router.get("/maintenance/requests")
def landlord_requests(urgency: str | None = None, status: str | None = None, category: str | None = None,
                      property_id: int | None = None, landlord: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    urgency_rank = case((m.MaintenanceRequest.ai_urgency == "emergency", 4),
                        (m.MaintenanceRequest.ai_urgency == "high", 3),
                        (m.MaintenanceRequest.ai_urgency == "medium", 2),
                        (m.MaintenanceRequest.ai_urgency == "low", 1), else_=0)
    stmt = select(m.MaintenanceRequest).join(m.Unit, m.Unit.id == m.MaintenanceRequest.unit_id).join(m.Property, m.Property.id == m.Unit.property_id).where(m.Property.landlord_id == landlord.id).order_by(urgency_rank.desc(), m.MaintenanceRequest.created_at.desc())
    if urgency: stmt = stmt.where(m.MaintenanceRequest.ai_urgency == urgency)
    if status: stmt = stmt.where(m.MaintenanceRequest.status == status)
    if category: stmt = stmt.where(m.MaintenanceRequest.ai_category == category)
    if property_id: stmt = stmt.where(m.Property.id == property_id)
    result = []
    for req in db.scalars(stmt).all():
        unit = db.get(m.Unit, req.unit_id); prop = db.get(m.Property, unit.property_id)
        conv = db.get(m.MaintenanceConversation, req.conversation_id) if req.conversation_id else None
        result.append({"id": req.id, "tenant_id": req.tenant_id, "tenant": db.get(m.User, req.tenant_id).full_name,
            "unit": unit.unit_number, "property": prop.name, "description": req.description, "status": req.status,
            "urgency": req.ai_urgency, "category": req.ai_category, "summary": req.ai_summary,
            "likely_cause": req.ai_likely_cause, "tried_self_help": req.tried_self_help,
            "created_at": req.created_at, "conversation": _conversation_out(db, conv, landlord) if conv else None})
    return result


@router.patch("/maintenance/requests/{request_id}/status")
def update_request_status(request_id: int, body: dict, landlord: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    req = db.get(m.MaintenanceRequest, request_id)
    if req is None:
        raise HTTPException(404, "Maintenance request not found")
    unit = db.get(m.Unit, req.unit_id); prop = db.get(m.Property, unit.property_id)
    if prop.landlord_id != landlord.id:
        raise HTTPException(404, "Maintenance request not found")
    status = body.get("status")
    if status not in {"received", "in_progress", "awaiting_parts", "resolved"}:
        raise HTTPException(400, "Status must be received, in_progress, awaiting_parts, or resolved")
    req.status = status
    if status == "resolved": req.resolved_at = m.utcnow()
    if req.conversation_id:
        db.add(m.MaintenanceMessage(conversation_id=req.conversation_id, role="bot", text=f"Your landlord updated report MR-{req.id:06d}: {status.replace('_', ' ')}."))
        conv = db.get(m.MaintenanceConversation, req.conversation_id)
        tenant = db.get(m.User, req.tenant_id)
        # Status acknowledgement is saved in chat; external contact delivery follows the shared sender policy.
        settings = db.scalar(select(m.AgencyReminderSettings).where(m.AgencyReminderSettings.agency_id == landlord.id))
        channels = settings.enabled_channels if settings else []
        for channel in channels:
            if channel == "email" and tenant.email_opt_in and tenant.email:
                recipient = tenant.email
            elif channel in {"sms", "whatsapp"} and getattr(tenant, f"{channel}_opt_in", False) and tenant.phone:
                recipient = tenant.phone
            else:
                continue
            try: send_with_retries(build_sender(channel), recipient, f"Maintenance update MR-{req.id:06d}", f"Your landlord updated your report: {status.replace('_', ' ')}.")
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Tenant maintenance status notification failed")
    db.commit()
    return {"id": req.id, "status": req.status}
