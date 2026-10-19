<<<<<<< HEAD
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..deps import get_current_user
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, hash_password, verify_password
=======
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.security import create_access_token, hash_password, verify_password
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3

router = APIRouter(prefix="/auth", tags=["auth"])


<<<<<<< HEAD
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
=======
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.scalar(
        select(User).where((User.email == payload.email) | (User.id_number == payload.id_number))
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email or ID number is already registered")
    user = User(
        email=payload.email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        id_number=payload.id_number,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
