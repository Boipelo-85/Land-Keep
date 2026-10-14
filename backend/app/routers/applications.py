from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import Application, CreditCheck, Lease, Unit, User
from app.schemas import ApplicationCreate, ApplicationResponse, DecisionRequest
from app.services.credit import recommendation_for
from app.services.notifications import notify

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def apply(
    payload: ApplicationCreate,
    tenant: User = Depends(require_role("tenant")),
    db: Session = Depends(get_db),
):
    if not payload.consent:
        raise HTTPException(status_code=400, detail="Consent is required to run a credit check")
    unit = db.get(Unit, payload.unit_id)
    if unit is None or not unit.is_vacant:
        raise HTTPException(status_code=404, detail="Vacant unit not found")
    prior = db.scalar(
        select(Application).where(
            Application.tenant_id == tenant.id,
            Application.unit_id == unit.id,
            Application.status.notin_(["declined", "withdrawn"]),
        )
    )
    if prior is not None:
        raise HTTPException(status_code=409, detail="You already have an active application for this unit")
    application = Application(tenant_id=tenant.id, unit_id=unit.id, consent_given=True)
    db.add(application)
    db.flush()
    score, recommendation = recommendation_for(tenant)
    application.status = recommendation
    db.add(CreditCheck(application_id=application.id, score=score, recommendation=recommendation))
    notify(db, tenant.id, f"Application {application.id} is {recommendation}.")
    db.commit()
    return ApplicationResponse(
        id=application.id,
        unit_id=unit.id,
        status=application.status,
        credit_score=score,
        recommendation=recommendation,
    )


@router.get("/{application_id}", response_model=ApplicationResponse)
def track_application(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    unit = db.get(Unit, application.unit_id)
    if user.role != "landlord" and application.tenant_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot view this application")
    if user.role == "landlord" and unit.landlord_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot view this application")
    credit_check = db.scalar(select(CreditCheck).where(CreditCheck.application_id == application.id))
    return ApplicationResponse(
        id=application.id,
        unit_id=application.unit_id,
        status=application.status,
        credit_score=credit_check.score,
        recommendation=credit_check.recommendation,
    )


@router.post("/{application_id}/decision", response_model=ApplicationResponse)
def decide_application(
    application_id: int,
    payload: DecisionRequest,
    landlord: User = Depends(require_role("landlord")),
    db: Session = Depends(get_db),
):
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    unit = db.get(Unit, application.unit_id)
    if unit.landlord_id != landlord.id:
        raise HTTPException(status_code=403, detail="You do not manage this unit")
    if not unit.is_vacant or db.scalar(select(Lease).where(Lease.application_id == application.id)):
        raise HTTPException(status_code=409, detail="Application can no longer be decided")
    application.status = payload.decision
    notify(db, application.tenant_id, f"Your application {application.id} was {payload.decision}.")
    credit_check = db.scalar(select(CreditCheck).where(CreditCheck.application_id == application.id))
    db.commit()
    return ApplicationResponse(
        id=application.id,
        unit_id=application.unit_id,
        status=application.status,
        credit_score=credit_check.score,
        recommendation=credit_check.recommendation,
    )
