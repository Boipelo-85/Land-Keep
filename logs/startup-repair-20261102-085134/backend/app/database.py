"""Database connection. SQLite by default; set LANDKEEP_DATABASE_URL to use PostgreSQL."""
import os
from pathlib import Path

<<<<<<< HEAD
from dotenv import load_dotenv

=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
<<<<<<< HEAD
load_dotenv(BASE_DIR / ".env")
=======
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
DATABASE_URL = os.getenv("LANDKEEP_DATABASE_URL", f"sqlite:///{BASE_DIR / 'landkeep.db'}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
