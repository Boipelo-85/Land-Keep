"""Tenant applications: apply -> credit check -> decision -> (convert, see leases.py).

Roles:
- applicant (role "tenant"): submit, track their own applications
- landlord: sees applications for their own units only, runs the credit check, decides
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import get_current_user, require_landlord, require_tenant
from ..schemas import ApplicationIn, DecisionIn
from ..services.credit import MockCreditBureau, recommend
from ..services.notifications import send_notification

router = APIRouter(prefix="/applications", tags=["applications"])

# The credit bureau is swappable: any object with .check(id_number, monthly_income).
credit_service = MockCreditBureau()


# ---- helpers --------------------------------------------------------------------------
def log_status(db: Session, app: m.TenantApplication, status: str, note: str, by: Optional[int]) -> None:
    """Change the application status and record it on the tracking timeline."""
    app.status = status
    db.add(m.ApplicationStatusHistory(application_id=app.id, status=status, note=note, changed_by_id=by))


def unit_and_property(db: Session, app: m.TenantApplication):
    unit = db.get(m.Unit, app.unit_id)
    return unit, db.get(m.Property, unit.property_id)


def load_for_user(db: Session, app_id: int, user: m.User) -> m.TenantApplication:
    """Fetch an application the user is allowed to see. Others get 404 so existence is not leaked."""
    app = db.get(m.TenantApplication, app_id)
    if app is not None:
        _, prop = unit_and_property(db, app)
        allowed = app.applicant_id == user.id if user.role == "tenant" else prop.landlord_id == user.id
        if allowed:
            return app
    raise HTTPException(404, "Application not found")


def serialize(db: Session, app: m.TenantApplication, timeline: bool = False) -> dict:
    unit, prop = unit_and_property(db, app)
    applicant = db.get(m.User, app.applicant_id)
    data = {
        "id": app.id,
        "reference_no": app.reference_no,
        "status": app.status,
        "unit": {"id": unit.id, "unit_number": unit.unit_number, "property": prop.name,
                 "monthly_rent": unit.monthly_rent},
        "applicant": {"id": applicant.id, "full_name": applicant.full_name,
                      "email": applicant.email, "phone": applicant.phone},
        "monthly_income": app.monthly_income,
        "employer": app.employer,
        "id_number": "*" * 9 + app.id_number[-4:],  # POPIA: show only what is needed
        "rent_to_income": round(unit.monthly_rent / app.monthly_income, 2),
        "consent_given": app.consent_given,
        "consent_at": app.consent_at,
        "credit_score": app.credit_score,
        "recommendation": app.recommendation,
        "decided_at": app.decided_at,
        "created_at": app.created_at,
    }
    if timeline:
        data["timeline"] = [{"status": h.status, "note": h.note, "at": h.created_at} for h in app.history]
    return data


# ---- applicant ------------------------------------------------------------------------
@router.post("", status_code=201)
def submit_application(body: ApplicationIn, user: m.User = Depends(require_tenant),
                       db: Session = Depends(get_db)):
    if not body.consent_given:
        raise HTTPException(400, "Consent to a credit check is required to apply")
    unit = db.get(m.Unit, body.unit_id)
    if unit is None or unit.status != "vacant":
        raise HTTPException(400, "This unit is not available")
    open_statuses = ("submitted", "under_review", "approved", "lease_issued")
    duplicate = db.scalar(select(m.TenantApplication).where(
        m.TenantApplication.applicant_id == user.id, m.TenantApplication.unit_id == unit.id,
        m.TenantApplication.status.in_(open_statuses)))
    if duplicate:
        raise HTTPException(409, f"You already have an open application for this unit ({duplicate.reference_no})")

    app = m.TenantApplication(reference_no=uuid.uuid4().hex[:30], applicant_id=user.id, unit_id=unit.id,
                              monthly_income=body.monthly_income, employer=body.employer,
                              id_number=body.id_number, consent_given=True,
                              consent_at=m.utcnow(), status="submitted")
    db.add(app)
    db.flush()
    app.reference_no = f"LK-{app.created_at.year}-{app.id:05d}"
    log_status(db, app, "submitted", "Application received", user.id)

    _, prop = unit_and_property(db, app)
    landlord = db.get(m.User, prop.landlord_id)
    send_notification(db, user, "application_received", ref=app.reference_no, unit=unit.unit_number)
    send_notification(db, landlord, "new_application_landlord", channels=("email",),
                      applicant=user.full_name, ref=app.reference_no, unit=unit.unit_number)
    db.commit()
    return serialize(db, app, timeline=True)


@router.get("/mine")
def my_applications(user: m.User = Depends(require_tenant), db: Session = Depends(get_db)):
    apps = db.scalars(select(m.TenantApplication).where(m.TenantApplication.applicant_id == user.id)
                      .order_by(m.TenantApplication.created_at.desc())).all()
    return [serialize(db, a) for a in apps]


# ---- landlord -------------------------------------------------------------------------
@router.get("")
def list_applications(status: Optional[str] = None, user: m.User = Depends(require_landlord),
                      db: Session = Depends(get_db)):
    stmt = (select(m.TenantApplication)
            .join(m.Unit, m.Unit.id == m.TenantApplication.unit_id)
            .join(m.Property, m.Property.id == m.Unit.property_id)
            .where(m.Property.landlord_id == user.id)
            .order_by(m.TenantApplication.created_at.desc()))
    if status:
        stmt = stmt.where(m.TenantApplication.status == status)
    return [serialize(db, a) for a in db.scalars(stmt).all()]


@router.post("/{app_id}/credit-check")
def run_credit_check(app_id: int, user: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    """Landlord verifies the applicant: mock credit score + rent-to-income -> recommendation."""
    app = load_for_user(db, app_id, user)
    if app.status != "submitted":
        raise HTTPException(409, f"Credit check can only run on a new application (status is {app.status})")
    if not app.consent_given:
        raise HTTPException(400, "No recorded consent for a credit check")
    unit, _ = unit_and_property(db, app)
    result = credit_service.check(app.id_number, app.monthly_income)
    app.credit_score = result.score
    app.credit_checked_at = m.utcnow()
    app.recommendation = recommend(result.score, app.monthly_income, unit.monthly_rent)
    log_status(db, app, "under_review",
               f"Credit check done ({result.source}). System recommendation: {app.recommendation}", user.id)
    db.commit()
    return serialize(db, app, timeline=True)


@router.post("/{app_id}/decision")
def decide(app_id: int, body: DecisionIn, user: m.User = Depends(require_landlord),
           db: Session = Depends(get_db)):
    """Landlord approves or rejects. The system only recommends; this is the real decision."""
    app = load_for_user(db, app_id, user)
    if app.status != "under_review":
        raise HTTPException(409, "Run the credit check first, and only decide once")
    app.decision_by = user.id
    app.decided_at = m.utcnow()
    note = f"Landlord {body.decision} the application"
    if body.note:
        note += f": {body.note}"
    log_status(db, app, body.decision, note, user.id)

    unit, _ = unit_and_property(db, app)
    applicant = db.get(m.User, app.applicant_id)
    template = "application_approved" if body.decision == "approved" else "application_rejected"
    send_notification(db, applicant, template, ref=app.reference_no, unit=unit.unit_number)
    db.commit()
    return serialize(db, app, timeline=True)


# ---- tracking (applicant or landlord) -------------------------------------------------
@router.get("/{app_id}")
def track_application(app_id: int, user: m.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return serialize(db, load_for_user(db, app_id, user), timeline=True)
