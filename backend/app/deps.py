<<<<<<< HEAD
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
=======
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        user_id = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
    return user


def require_role(role: str):
<<<<<<< HEAD
    def checker(user: m.User = Depends(get_current_user)) -> m.User:
        if user.role != role:
            raise HTTPException(403, f"Only a {role} can do this")
        return user

    return checker


require_landlord = require_role("landlord")
require_tenant = require_role("tenant")
=======
    def role_guard(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{role.title()} access required")
        return user

    return role_guard
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
