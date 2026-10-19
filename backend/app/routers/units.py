from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

<<<<<<< HEAD
from .. import models as m
from ..database import get_db
=======
from app.database import get_db
from app.deps import get_current_user
from app.models import Unit, User
from app.schemas import UnitResponse
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3

router = APIRouter(prefix="/units", tags=["units"])


<<<<<<< HEAD
@router.get("/vacant")
def vacant_units(db: Session = Depends(get_db)):
    """Units an applicant can apply for. Units with a lease already in progress are hidden."""
    taken = select(m.Lease.unit_id).where(m.Lease.status.in_(("pending", "active")))
    rows = db.execute(
        select(m.Unit, m.Property)
        .join(m.Property, m.Property.id == m.Unit.property_id)
        .where(m.Unit.status == "vacant", m.Unit.id.not_in(taken))
        .order_by(m.Property.name, m.Unit.unit_number)
    ).all()
    return [{"id": u.id, "unit_number": u.unit_number, "bedrooms": u.bedrooms,
             "monthly_rent": u.monthly_rent, "property": p.name, "address": p.address, "city": p.city}
            for u, p in rows]
=======
@router.get("", response_model=list[UnitResponse])
def list_vacant_units(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(select(Unit).where(Unit.is_vacant.is_(True)).order_by(Unit.id)).all()
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
