<<<<<<< HEAD
"""Database connection. SQLite by default; set LANDKEEP_DATABASE_URL to use PostgreSQL."""
=======
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
<<<<<<< HEAD
DATABASE_URL = os.getenv("LANDKEEP_DATABASE_URL", f"sqlite:///{BASE_DIR / 'landkeep.db'}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
=======
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(BASE_DIR / 'landkeep.db').as_posix()}",
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_options = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_options)
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
<<<<<<< HEAD
    """FastAPI dependency: one session per request."""
=======
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
