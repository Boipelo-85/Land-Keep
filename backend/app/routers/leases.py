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
