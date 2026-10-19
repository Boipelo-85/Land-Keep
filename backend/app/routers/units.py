from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db

router = APIRouter(prefix="/units", tags=["units"])


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
