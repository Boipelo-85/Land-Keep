<<<<<<< HEAD
"""One place to send every email and SMS.

Every message is saved in the Notification table and delivered through
`_deliver`. Today `_deliver` prints to the console (perfect for a demo). To go live,
swap its body for SMTP or Twilio. WhatsApp later is just another channel here.
"""
from sqlalchemy.orm import Session

from .. import models as m

# template name -> (subject, body). Placeholders are filled from keyword arguments.
TEMPLATES = {
    "application_received": (
        "We received your application",
        "Hi {name}, we received your application {ref} for unit {unit}. "
        "You can track it in LandKeep with this reference number.",
    ),
    "new_application_landlord": (
        "New tenant application",
        "Hi {name}, {applicant} applied for unit {unit} (reference {ref}). Review it in LandKeep.",
    ),
    "application_approved": (
        "Your application was approved",
        "Good news {name}! Your application {ref} for unit {unit} was approved. "
        "Your lease agreement will follow shortly.",
    ),
    "application_rejected": (
        "Update on your application",
        "Hi {name}, unfortunately your application {ref} for unit {unit} was not successful.",
    ),
    "lease_ready": (
        "Your lease agreement is ready",
        "Hi {name}, your lease for unit {unit} is ready. Log in to LandKeep to read it and accept.",
    ),
    "lease_accepted_landlord": (
        "Lease accepted",
        "Hi {name}, {tenant} accepted the lease for unit {unit}. They are now an active tenant.",
    ),
    "maintenance_received": (
        "We received your maintenance request",
        "Hi {name}, we received your report for unit {unit}: \"{summary}\". "
        "Your landlord will follow up in LandKeep.",
    ),
}


def _deliver(channel: str, user: m.User, subject: str, body: str) -> str:
    """Stand-in delivery: print to the console. Replace with SMTP / Twilio later."""
    target = user.email if channel == "email" else user.phone
    print(f"[{channel.upper()} -> {target}] {subject}: {body}")
    return "sent"


def send_notification(db: Session, user: m.User, template: str,
                      channels: tuple = ("email", "sms"), **context) -> list[m.Notification]:
    subject, body_template = TEMPLATES[template]
    body = body_template.format(name=user.full_name.split()[0], **context)
    sent = []
    for channel in channels:
        if channel == "sms" and not user.phone:
            continue
        status = _deliver(channel, user, subject, body)
        note = m.Notification(user_id=user.id, channel=channel, template=template,
                              subject=subject, body=body, status=status)
        db.add(note)
        sent.append(note)
    return sent
=======
import logging

from sqlalchemy.orm import Session

from app.models import Notification

logger = logging.getLogger(__name__)


def notify(db: Session, user_id: int, message: str, channel: str = "in_app") -> Notification:
    if channel not in {"in_app", "email", "sms"}:
        raise ValueError("Notification channel must be in_app, email, or sms")
    notification = Notification(user_id=user_id, channel=channel, message=message)
    db.add(notification)
    logger.info("Recorded %s alert for user %s", channel, user_id)
    return notification
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
