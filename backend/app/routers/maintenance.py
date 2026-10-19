"""Tenant maintenance reports: describe a problem, optionally attach a photo."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import BASE_DIR, get_db
from ..deps import require_tenant
from ..schemas import MaintenanceOut
from ..services.notifications import send_notification

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
