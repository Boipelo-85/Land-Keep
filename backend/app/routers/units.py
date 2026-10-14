from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Unit, User
from app.schemas import UnitResponse

router = APIRouter(prefix="/units", tags=["units"])


@router.get("", response_model=list[UnitResponse])
def list_vacant_units(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(select(Unit).where(Unit.is_vacant.is_(True)).order_by(Unit.id)).all()
