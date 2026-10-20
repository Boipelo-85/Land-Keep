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
from datetime import timedelta
from sqlalchemy import select

logger = logging.getLogger(__name__)


def scheduled_rent_reminders() -> None:
    """Run the daily reminder evaluation with its own database session."""
    try:
        with SessionLocal() as db:
            result = run_reminders(db)
        logger.info("Month-end rent reminder job completed: %s", result["summary"])
    except Exception:
        logger.exception("Month-end rent reminder job failed")


def scheduled_maintenance_escalations() -> None:
    """Re-notify agencies about high/emergency chatbot reports still unacknowledged."""
    hours = max(1, int(os.getenv("MAINTENANCE_URGENT_ESCALATION_HOURS", "2")))
    try:
        with SessionLocal() as db:
            rows = db.scalars(select(models.MaintenanceRequest).where(
                models.MaintenanceRequest.source == "chatbot",
                models.MaintenanceRequest.ai_urgency.in_(["high", "emergency"]),
                models.MaintenanceRequest.status == "open",
                models.MaintenanceRequest.created_at <= models.utcnow() - timedelta(hours=hours),
            )).all()
            for req in rows:
                conv = db.get(models.MaintenanceConversation, req.conversation_id)
                if conv is None:
                    continue
                agency = db.get(models.User, conv.agency_id)
                from .routers.maintenance import _notify_landlord
                _notify_landlord(db, conv, f"Unacknowledged {req.ai_urgency} maintenance report MR-{req.id:06d}",
                    f"This urgent report for {agency.full_name} is still open: {req.ai_summary}. Please review it in LandKeep.", True)
        logger.info("Urgent maintenance escalation check completed")
    except Exception:
        logger.exception("Urgent maintenance escalation job failed")


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
    scheduler.add_job(scheduled_maintenance_escalations, "interval",
        minutes=max(5, int(os.getenv("MAINTENANCE_ESCALATION_CHECK_MINUTES", "30"))),
        id="maintenance_urgent_escalations", replace_existing=True, coalesce=True, max_instances=1)
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
