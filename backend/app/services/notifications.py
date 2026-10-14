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
