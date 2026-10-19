"""LandKeep API.  Run:  uvicorn app.main:app --reload   (docs at http://localhost:8000/docs)"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (registers the tables)
from .database import Base, SessionLocal, engine
from .routers import applications, auth, leases, maintenance, reminders, units
from .services.agency_reminders import TIMEZONE_NAME, run_reminders

logger = logging.getLogger(__name__)


def scheduled_rent_reminders() -> None:
    """Run the daily reminder evaluation with its own database session."""
    try:
        with SessionLocal() as db:
            result = run_reminders(db)
        logger.info("Month-end rent reminder job completed: %s reminders", len(result["reminders"]))
    except Exception:
        logger.exception("Month-end rent reminder job failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    send_time = os.getenv("LANDKEEP_REMINDER_SEND_TIME", "08:00")
    hour, minute = (int(value) for value in send_time.split(":", 1))
    scheduler = BackgroundScheduler(timezone=TIMEZONE_NAME)
    scheduler.add_job(
        scheduled_rent_reminders,
        CronTrigger(hour=hour, minute=minute, timezone=TIMEZONE_NAME),
        id="month_end_rent_reminders",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

app = FastAPI(title="LandKeep API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(engine)

app.include_router(auth.router)
app.include_router(units.router)
app.include_router(applications.router)
app.include_router(leases.router)
app.include_router(maintenance.router)
app.include_router(reminders.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
