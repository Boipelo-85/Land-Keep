"""Shared FastAPI dependencies: current user and role guards."""
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models as m
from .database import get_db
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> m.User:
    if creds is None:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_token(creds.credentials)
    user = db.get(m.User, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Invalid or expired token")
    return user


def require_role(role: str):
    def checker(user: m.User = Depends(get_current_user)) -> m.User:
        if user.role != role:
            raise HTTPException(403, f"Only a {role} can do this")
        return user

    return checker


require_landlord = require_role("landlord")
require_tenant = require_role("tenant")
