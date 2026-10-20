"""Safety-first maintenance chat orchestration and Claude vision adapter."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import BASE_DIR
from .maintenance_storage import read_private_attachment

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "maintenance_chat_system.txt"
DISCLAIMER = "These suggestions are general guidance, not a professional inspection."
TRIGGERS = {
    "gas smell": "gas", "smell of gas": "gas", "smell gas": "gas", "gas leak": "gas",
    "exposed wiring": "electrical", "live wire": "electrical", "sparking": "electrical",
    "sparks": "electrical", "burning smell": "fire", "smoke": "fire", "fire": "fire",
    "flooding": "flood", "flood": "flood", "burst pipe": "flood",
    "ceiling collapse": "collapse", "collapsed ceiling": "collapse",
    "sewage overflow": "sewage", "sewage is overflowing": "sewage", "sewage overflowing": "sewage",
    "structural crack": "structure", "crack in the wall": "structure",
    "broken door": "security", "broken lock": "security", "door won't lock": "security",
    "cannot lock": "security", "can't lock": "security", "no security": "security", "not secure": "security",
}


class Analysis(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)
    category: str
    urgency: str
    summary: str = Field(max_length=500)
    likely_cause: str = Field(max_length=500)
    confidence: float = Field(ge=0, le=1)
    diy_appropriate: bool
    suggested_steps: list[str] = Field(default_factory=list, max_length=8)
    needs_follow_up: bool = False
    follow_up_question: str | None = None


def detect_emergency(text: str) -> str | None:
    normalized = " ".join(text.lower().replace("’", "'").split())
    return next((kind for phrase, kind in TRIGGERS.items() if phrase in normalized), None)


def wants_landlord(text: str) -> bool:
    normalized = " ".join(text.lower().replace("’", "'").split())
    return any(phrase in normalized for phrase in (
        "report this", "report it", "tell my landlord", "contact my landlord",
        "i want the landlord", "speak to my landlord", "send this to my landlord",
        "i want to report", "landlord please",
    ))


def emergency_reply(kind: str) -> str:
    extra = {
        "gas": "Do not operate switches or flames. Leave the area and call local emergency services or the gas provider from outside.",
        "electrical": "Keep away and do not touch wires or equipment. Leave the area. Switch off power at the main only if you can do so safely.",
        "fire": "Leave the area and call local emergency services. Do not try to fight a spreading fire.",
        "flood": "Keep away from water near electricity. Turn off water or power only if it is safe, then contact emergency help if anyone is at risk.",
        "collapse": "Leave the affected area and keep others away. Contact local emergency services if anyone may be in danger.",
        "sewage": "Keep people and pets away from the affected area and contact your landlord urgently.",
        "structure": "Keep away from the affected area and contact your landlord urgently. Leave if the building may be unsafe.",
        "security": "Move somewhere secure and contact your landlord urgently. Call local emergency services if you are in immediate danger.",
    }.get(kind, "Move to a safe place and contact your landlord urgently.")
    return f"This may be an emergency. {extra} I have sent an urgent report to your landlord. {DISCLAIMER}"


def fallback_analysis() -> Analysis:
    return Analysis(reply=f"I couldn't safely assess this just now, so I sent this to your landlord for human review. {DISCLAIMER}",
                    category="other", urgency="medium", summary="Needs human review; AI analysis unavailable",
                    likely_cause="Unknown", confidence=0, diy_appropriate=False)


def analyze_with_claude(text: str, image_paths: list[str]) -> Analysis:
    """Call Claude with vision; no API key means safe human-review fallback."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    import anthropic

    schema: dict[str, Any] = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "reply": {"type": "string"}, "category": {"type": "string"},
            "urgency": {"type": "string"}, "summary": {"type": "string"},
            "likely_cause": {"type": "string"}, "confidence": {"type": "number"},
            "diy_appropriate": {"type": "boolean"}, "suggested_steps": {"type": "array", "items": {"type": "string"}},
            "needs_follow_up": {"type": "boolean"}, "follow_up_question": {"type": ["string", "null"]},
        }, "required": ["reply", "category", "urgency", "summary", "likely_cause", "confidence", "diy_appropriate", "suggested_steps", "needs_follow_up", "follow_up_question"],
    }
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for path in image_paths:
        data = read_private_attachment(path)
        suffix = Path(path).suffix.lower()
        media = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[suffix]
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode("ascii")}})
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=float(os.getenv("MAINTENANCE_AI_TIMEOUT_SECONDS", "20")), max_retries=0)
    response = client.messages.create(
        model=os.getenv("MAINTENANCE_AI_MODEL", "claude-sonnet-5-5"), max_tokens=1000,
        system=PROMPT_PATH.read_text(encoding="utf-8"),
        tools=[{"name": "maintenance_assessment", "description": "Return a validated maintenance assessment", "input_schema": schema}],
        tool_choice={"type": "tool", "name": "maintenance_assessment"},
        messages=[{"role": "user", "content": content}],
    )
    block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise ValueError("Claude returned no structured assessment")
    result = Analysis.model_validate(block.input)
    if result.category not in m.CHAT_MAINTENANCE_CATEGORIES or result.urgency not in m.CHAT_MAINTENANCE_URGENCIES:
        raise ValueError("Claude returned unsupported category or urgency")
    # Electrical and structural topics are always referred to a human.
    if result.category == "electrical" or any(w in text.lower() for w in ("gas", "structural", "crack in the wall")):
        result.diy_appropriate = False
        result.suggested_steps = []
        if result.category == "electrical":
            result.reply = "Electrical problems can be dangerous. Please do not touch wiring or electrical equipment. I recommend your landlord or a qualified electrician assess it."
    result.reply = f"{result.reply.strip()} {DISCLAIMER}"
    if result.needs_follow_up and result.follow_up_question:
        result.reply += f"\n\n{result.follow_up_question}"
    elif result.diy_appropriate:
        result.reply += "\n\nDid that solve it?"
    return result


def within_limits(db: Session, tenant_id: int, conversation_id: int) -> None:
    max_messages = int(os.getenv("MAINTENANCE_MAX_MESSAGES_PER_CONVERSATION", "20"))
    count = db.scalar(select(func.count(m.MaintenanceMessage.id)).where(m.MaintenanceMessage.conversation_id == conversation_id)) or 0
    if count >= max_messages:
        raise ValueError("This chat reached its message limit. Please report it to your landlord.")
    daily_limit = int(os.getenv("MAINTENANCE_TENANT_DAILY_MESSAGE_LIMIT", "30"))
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    daily = db.scalar(select(func.count(m.MaintenanceMessage.id)).join(m.MaintenanceConversation).where(
        m.MaintenanceConversation.tenant_id == tenant_id, m.MaintenanceMessage.role == "tenant",
        m.MaintenanceMessage.created_at >= cutoff)) or 0
    if daily >= daily_limit:
        raise ValueError("You reached today's chat limit. Please contact your landlord directly.")


def validate_analysis(value: Any) -> Analysis:
    try:
        result = Analysis.model_validate(value)
        if result.category not in m.CHAT_MAINTENANCE_CATEGORIES or result.urgency not in m.CHAT_MAINTENANCE_URGENCIES:
            raise ValueError("unsupported value")
        return result
    except (ValidationError, ValueError, TypeError):
        return fallback_analysis()
