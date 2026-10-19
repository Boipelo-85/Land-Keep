from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import get_current_user
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: m.User) -> dict:
    return {"id": user.id, "role": user.role, "full_name": user.full_name,
            "email": user.email, "phone": user.phone}


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Public sign-up. New accounts are always tenants (applicants); landlords are created by the seed."""
    email = body.email.lower().strip()
    if db.scalar(select(m.User).where(m.User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = m.User(role="tenant", full_name=body.full_name.strip(), email=email,
                  phone=body.phone, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.id), "user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower().strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"token": create_token(user.id), "user": user_out(user)}


@router.get("/me")
def me(user: m.User = Depends(get_current_user)):
    return user_out(user)
