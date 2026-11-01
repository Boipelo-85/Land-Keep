"""Convert an approved applicant into a tenant, issue the lease, and let the tenant accept it."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import BASE_DIR, get_db
from ..deps import get_current_user, require_landlord, require_tenant
from ..schemas import ConvertIn
from ..services.leases import add_months, build_lease_pdf, generate_charges
from ..services.notifications import send_notification
from .applications import load_for_user, log_status, unit_and_property

router = APIRouter(tags=["leases"])


def lease_out(lease: m.Lease, unit: m.Unit, prop: m.Property) -> dict:
    return {"id": lease.id, "status": lease.status, "unit": unit.unit_number, "property": prop.name,
            "start_date": lease.start_date, "end_date": lease.end_date, "monthly_rent": lease.monthly_rent,
            "deposit": lease.deposit, "due_day": lease.due_day, "accepted_at": lease.accepted_at,
            "pdf_url": f"/leases/{lease.id}/pdf", "application_id": lease.application_id}


def _load_lease(db: Session, lease_id: int, user: m.User):
    lease = db.get(m.Lease, lease_id)
    if lease is not None:
        unit = db.get(m.Unit, lease.unit_id)
        prop = db.get(m.Property, unit.property_id)
        allowed = lease.tenant_id == user.id if user.role == "tenant" else prop.landlord_id == user.id
        if allowed:
            return lease, unit, prop
    raise HTTPException(404, "Lease not found")


@router.post("/applications/{app_id}/convert", status_code=201)
def convert_to_tenant(app_id: int, body: ConvertIn, user: m.User = Depends(require_landlord),
                      db: Session = Depends(get_db)):
    """One click: the approved applicant becomes a tenant of the unit and gets a lease to accept."""
    app = load_for_user(db, app_id, user)
    if app.status != "approved":
        raise HTTPException(409, f"Only an approved application can be converted (status is {app.status})")
    unit, prop = unit_and_property(db, app)
    clash = db.scalar(select(m.Lease).where(m.Lease.unit_id == unit.id,
                                            m.Lease.status.in_(("pending", "active"))))
    if unit.status != "vacant" or clash:
        raise HTTPException(409, "This unit already has a lease in progress")

    tenant = db.get(m.User, app.applicant_id)
    lease = m.Lease(unit_id=unit.id, tenant_id=tenant.id, application_id=app.id,
                    start_date=body.start_date,
                    end_date=add_months(body.start_date, body.term_months) - timedelta(days=1),
                    monthly_rent=unit.monthly_rent,
                    deposit=body.deposit if body.deposit is not None else unit.monthly_rent,
                    due_day=body.due_day, status="pending")
    db.add(lease)
    db.flush()
    lease.pdf_path = build_lease_pdf(lease, unit, prop, db.get(m.User, prop.landlord_id), tenant)
    log_status(db, app, "lease_issued", "Lease agreement generated and sent to the applicant", user.id)
    send_notification(db, tenant, "lease_ready", unit=unit.unit_number)
    db.commit()
    return lease_out(lease, unit, prop)


@router.get("/leases/mine")
def my_leases(user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    leases = db.scalars(select(m.Lease).where(m.Lease.tenant_id == user.id)
                        .order_by(m.Lease.created_at.desc())).all()
    out = []
    for lease in leases:
        unit = db.get(m.Unit, lease.unit_id)
        out.append(lease_out(lease, unit, db.get(m.Property, unit.property_id)))
    return out


@router.get("/leases/{lease_id}/pdf")
def lease_pdf(lease_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    lease, _, _ = _load_lease(db, lease_id, user)
    path = BASE_DIR / lease.pdf_path if lease.pdf_path else None
    if path is None or not path.exists():
        raise HTTPException(404, "Lease document not found")
    return FileResponse(path, media_type="application/pdf", filename=f"lease_{lease.id}.pdf")


@router.post("/leases/{lease_id}/accept")
def accept_lease(lease_id: int, user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    """Tenant accepts: the lease goes live, the unit becomes occupied, rent charges start."""
    lease, unit, prop = _load_lease(db, lease_id, user)
    if lease.status != "pending":
        raise HTTPException(409, f"Lease is already {lease.status}")
    lease.status = "active"
    lease.accepted_at = m.utcnow()
    unit.status = "occupied"
    generate_charges(db, lease, upto=m.utcnow().date())

    app = db.get(m.TenantApplication, lease.application_id) if lease.application_id else None
    if app is not None:
        log_status(db, app, "active_tenant", "Tenant accepted the lease and moved in", user.id)
    landlord = db.get(m.User, prop.landlord_id)
    send_notification(db, landlord, "lease_accepted_landlord", channels=("email",),
                      tenant=user.full_name, unit=unit.unit_number)
    db.commit()
    return lease_out(lease, unit, prop)
