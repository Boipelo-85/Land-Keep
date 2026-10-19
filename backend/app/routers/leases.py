<<<<<<< HEAD
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
=======
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import Application, Lease, LeaseAcceptance, Unit, User
from app.schemas import LeaseAcceptanceResponse, LeaseResponse
from app.services.leases import accept_lease, create_lease, create_lease_pdf
from app.services.notifications import notify

router = APIRouter(prefix="/leases", tags=["leases"])


@router.post("/from-application/{application_id}", response_model=LeaseResponse, status_code=status.HTTP_201_CREATED)
def convert_application(
    application_id: int,
    landlord: User = Depends(require_role("landlord")),
    db: Session = Depends(get_db),
):
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    unit = db.get(Unit, application.unit_id)
    if unit.landlord_id != landlord.id:
        raise HTTPException(status_code=403, detail="You do not manage this unit")
    if application.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved applications can become leases")
    if not unit.is_vacant:
        raise HTTPException(status_code=409, detail="Unit is no longer vacant")
    if db.scalar(select(Lease).where(Lease.application_id == application.id)) is not None:
        raise HTTPException(status_code=409, detail="A lease already exists for this application")
    lease = create_lease(db, application, unit)
    notify(db, application.tenant_id, f"Lease {lease.id} is ready for acceptance.")
    db.commit()
    db.refresh(lease)
    return lease


@router.get("/{lease_id}/pdf")
def lease_pdf(
    lease_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lease = db.get(Lease, lease_id)
    if lease is None:
        raise HTTPException(status_code=404, detail="Lease not found")
    unit = db.get(Unit, lease.unit_id)
    if user.id not in {lease.tenant_id, unit.landlord_id}:
        raise HTTPException(status_code=403, detail="You are not a party to this lease")
    tenant = db.get(User, lease.tenant_id)
    pdf = create_lease_pdf(lease, tenant, unit)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="landkeep-lease-{lease.id}.pdf"'},
    )


@router.post("/{lease_id}/accept", response_model=LeaseAcceptanceResponse)
def accept(
    lease_id: int,
    tenant: User = Depends(require_role("tenant")),
    db: Session = Depends(get_db),
):
    lease = db.get(Lease, lease_id)
    if lease is None:
        raise HTTPException(status_code=404, detail="Lease not found")
    if lease.tenant_id != tenant.id:
        raise HTTPException(status_code=403, detail="You cannot accept this lease")
    if lease.status != "pending_acceptance":
        raise HTTPException(status_code=409, detail="Lease is not awaiting acceptance")
    db.add(LeaseAcceptance(lease_id=lease.id))
    charge = accept_lease(db, lease)
    db.commit()
    return LeaseAcceptanceResponse(lease_id=lease.id, status=lease.status, rent_charge_id=charge.id)
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
