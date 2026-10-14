import logging

from sqlalchemy.orm import Session

from app.models import Notification

logger = logging.getLogger(__name__)


def notify(db: Session, user_id: int, message: str, channel: str = "email") -> Notification:
    if channel not in {"email", "sms"}:
        raise ValueError("Notification channel must be email or sms")
    notification = Notification(user_id=user_id, channel=channel, message=message)
    db.add(notification)
    logger.info("Queued %s notification for user %s", channel, user_id)
    return notification
