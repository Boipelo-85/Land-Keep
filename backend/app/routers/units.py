<<<<<<< HEAD
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
=======
from fastapi import APIRouter, Depends
from sqlalchemy import select
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
<<<<<<< HEAD
from ..deps import require_landlord
from ..schemas import PropertyCreateIn, UnitCreateIn
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5

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
<<<<<<< HEAD


@router.get('/properties')
def my_properties(landlord: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.Property).where(m.Property.landlord_id == landlord.id).order_by(m.Property.name)).all()
    return [{'id': p.id, 'name': p.name, 'address': p.address, 'city': p.city} for p in rows]


@router.post('/properties', status_code=201)
def create_property(body: PropertyCreateIn, landlord: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    row = m.Property(landlord_id=landlord.id, **body.model_dump())
    db.add(row)
    db.commit()
    return {'id': row.id, 'name': row.name, 'address': row.address, 'city': row.city}


@router.get('/mine')
def my_units(landlord: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    reserved = select(m.Lease.unit_id).where(m.Lease.status.in_(('pending', 'active')))
    rows = db.execute(select(m.Unit, m.Property).join(m.Property).where(m.Property.landlord_id == landlord.id)
                      .order_by(m.Property.name, m.Unit.unit_number)).all()
    taken = set(db.scalars(reserved).all())
    return [{'id': u.id, 'property_id': p.id, 'property': p.name, 'unit_number': u.unit_number,
             'bedrooms': u.bedrooms, 'monthly_rent': u.monthly_rent, 'status': u.status,
             'listed_for_applications': u.status == 'vacant' and u.id not in taken,
             'address': p.address, 'city': p.city} for u, p in rows]


@router.post('', status_code=201)
def create_unit(body: UnitCreateIn, landlord: m.User = Depends(require_landlord), db: Session = Depends(get_db)):
    prop = db.scalar(select(m.Property).where(m.Property.id == body.property_id, m.Property.landlord_id == landlord.id))
    if prop is None:
        raise HTTPException(404, 'Property not found')
    duplicate = db.scalar(select(m.Unit.id).where(m.Unit.property_id == prop.id,
                          func.lower(m.Unit.unit_number) == body.unit_number.lower()))
    if duplicate:
        raise HTTPException(409, 'A unit with this number already exists at this property')
    unit = m.Unit(**body.model_dump(), status='vacant')
    db.add(unit)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'A unit with this number already exists at this property') from exc
    return {'id': unit.id, 'property_id': prop.id, 'property': prop.name, 'unit_number': unit.unit_number,
            'bedrooms': unit.bedrooms, 'monthly_rent': unit.monthly_rent, 'status': unit.status,
            'listed_for_applications': True, 'address': prop.address, 'city': prop.city}
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
