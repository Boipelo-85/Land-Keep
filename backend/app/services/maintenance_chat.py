"""Safety-first maintenance chat orchestration and Gemini vision adapter."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import BASE_DIR
from .maintenance_storage import read_private_attachment

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "maintenance_chat_system.txt"
DISCLAIMER = "These suggestions are general guidance, not a professional inspection."


class AnalysisOutputError(ValueError):
    """The AI provider answered but its structured assessment could not be trusted."""
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
    _from_local: bool = PrivateAttr(default=False)
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


def normalize_message(text: str) -> str:
    text = text.lower().replace("’", "'")
    for wrong, right in {"cant": "can't", "cnt": "can't", "cannnot": "cannot", "mu": "my", "kyes": "keys", "keeys": "keys"}.items():
        text = re.sub(r"\b" + wrong + r"\b", right, text)
    return " ".join(text.split()).strip(".!? ")


def key_issue(text: str) -> bool:
    text = normalize_message(text)
    return bool(re.search(r"\bkeys?\b|access card|locked out", text)) and any(
        phrase in text for phrase in ("lost", "missing", "can't find", "cannot find", "can't get", "locked out", "stolen", "need", "spare"))


def wants_landlord(text: str) -> bool:
    if key_issue(text):
        return True
    normalized = " ".join(text.lower().replace("’", "'").split())
    return any(phrase in normalized for phrase in (
        "report this", "report it", "tell my landlord", "contact my landlord",
        "i want the landlord", "speak to my landlord", "send this to my landlord",
        "i want to report", "landlord please", "spare key", "need a key", "need keys",
        "locked out", "lost key", "lost keys", "lost my key",
    ))


def landlord_followup_reply(text: str) -> str:
    """Acknowledge an escalated-chat update and offer only low-risk interim steps."""
    normalized = " ".join(text.lower().replace("’", "'").split())
    
    # Require an affirmative resolution, never a substring such as "not fixed".
    negative = re.search(r"\b(not|isn't|isnt|hasn't|hasnt|haven't|havent|never|unresolved)\b", normalized)
    resolved = re.search(r"\b(found (it|them|the keys?|my keys?)|it works now|all fixed|problem solved|issue resolved)\b", normalized)
    if resolved and not negative:
        return f"That's great! I'll note that you've resolved this issue. This chat is now closed. {DISCLAIMER}"

    # Lost or stolen keys - no DIY, ask security questions, point to landlord
    if any(term in normalized for term in ("lost my key", "lost all my keys", "lost the key", "lost keys", "keys are missing", "lost my apartment keys", "lost apartment keys", "lost my keys", "stolen key", "stolen keys", "stolen my keys")):
        advice = (
            "Are you locked out right now? Could someone else have access to your keys or address? "
            "Please contact your landlord or building manager immediately. "
            "They can help with authorised access, a locksmith, or securing the property if needed. "
            "Don't force the door or lock."
        )
    elif "locked out" in normalized or "lockout" in normalized:
        advice = (
            "If you are locked out right now, please contact your landlord or building manager immediately for assistance. "
            "Don't force the door or lock. If you're in immediate danger, call local emergency services."
        )
    elif "tap" in normalized and any(term in normalized for term in ("no water", "cant get water", "not getting water", "take out water")):
        advice = (
            "While you wait, check whether other taps work and note whether hot water, cold water, or both are affected. "
            "Don't remove the tap or fittings. If you notice a leak, keep water away from plugs and catch drips in a container."
        )
    elif any(term in normalized for term in ("leak", "leaking", "dripping", "burst pipe")):
        advice = (
            "If safe, place a container or towels under the leak and move belongings away. Keep water away from plugs and appliances. "
            "Only close a water valve if you know where it is and can reach it safely; don't dismantle plumbing."
        )
    elif any(term in normalized for term in ("blocked drain", "blocked sink", "blocked basin")):
        advice = (
            "Stop using that drain for now and remove only debris you can see at the surface. "
            "Don't mix drain cleaners or take pipes apart; tell your landlord if water is overflowing."
        )
    else:
        advice = (
            "While you wait, avoid taking equipment apart or trying repairs that need tools. Keep people away from anything unsafe. "
            "If the problem gets worse or anyone is in danger, move to a safe place and contact local emergency help."
        )
    return f"I've added this update to your maintenance report for your landlord. {advice} {DISCLAIMER}"


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


def interim_assessment(text: str) -> Analysis:
    """Deterministic interim guidance; not a trained classifier or a diagnosis."""
    normalized = text.lower().replace("’", "'")
    emergency = detect_emergency(text)
    if emergency:
        category = {"electrical": "electrical", "gas": "other", "fire": "electrical",
                    "flood": "plumbing", "sewage": "plumbing", "security": "doors_locks"}.get(emergency, "other")
        reply = emergency_reply(emergency).replace("I have sent an urgent report to your landlord. ", "")
        urgency = "emergency"
    elif re.search(r"\b(keys?|locks?|locked|security|burglar|gate|stolen)\b", normalized):
        category, urgency = "doors_locks", "high"
        reply = ("If you're locked out, wait somewhere safe and contact your landlord or building manager for authorised access or a locksmith. "
                 "If you're inside, avoid leaving without a way back in. Don't force or dismantle the lock. "
                 "Could someone else link the missing key to your address?")
    elif any(word in normalized for word in ("electri", "socket", "plug", "light", "wiring", "power", "switch")):
        category, urgency = "electrical", "medium"
        reply = ("Check whether there is an announced power interruption and note whether one fixture or the whole unit is affected. "
                 "Keep away from damaged fittings and don't open panels, touch wiring, or repeatedly reset a breaker. "
                 "Your landlord should arrange a qualified electrician. Is there heat, a burning smell, or sparking?")
    elif any(word in normalized for word in ("geyser", "hot water")):
        category, urgency = "appliance", "medium"
        reply = ("Check whether cold water still runs and whether there is an announced electricity or water interruption. "
                 "Don't open the geyser, touch its wiring, or operate reset controls. "
                 "Ask your landlord for a qualified technician. Is the geyser leaking?")
    elif "drain" in normalized or ("blocked" in normalized and any(word in normalized for word in ("sink", "toilet", "basin"))):
        category, urgency = "plumbing", "medium"
        reply = ("Stop using the blocked fixture and remove only loose debris visible at the surface if safe. "
                 "Don't mix chemicals or dismantle pipes. Keep children and pets away from dirty water. "
                 "Is water overflowing or backing up anywhere else?")
    elif any(word in normalized for word in ("leak", "drip", "pipe", "tap", "water", "toilet", "plumbing")):
        category, urgency = "plumbing", "medium"
        reply = ("For a leak, catch drips in a container if safe and move belongings away. Keep water away from plugs and appliances. "
                 "Only close a familiar, safely accessible water valve; don't dismantle fittings. "
                 "For no water, check whether other taps work and whether the building has a supply interruption. "
                 "Is it a slow drip, a steady flow, or no water at all?")
    elif any(word in normalized for word in ("damp", "mould", "mold", "roof", "ceiling")):
        category, urgency = "roof_damp", "medium"
        reply = ("Move belongings away from the damp area and ventilate if safe. Don't climb or touch a sagging ceiling, scrape mould, or mix cleaning chemicals. "
                 "Keep people away if material is loose. Is the area spreading or is water dripping?")
    else:
        category, urgency = "other", "medium"
        reply = ("Keep the affected area clear and stop using anything damaged. "
                 "Note when the problem occurs and take a photo only if safe. Don't use tools or dismantle fixtures. "
                 "Which item is affected, and what happens when you use it?")
    return Analysis(reply=reply, category=category, urgency=urgency,
                    summary=text[:500] or "Maintenance assistance requested", likely_cause="Requires assessment; not diagnosed",
                    confidence=0, diy_appropriate=False)


def conversational_fallback(transcript: str, *, escalated: bool = False) -> Analysis:
    """Use the latest tenant turn and earlier tenant context when AI is unavailable."""
    turns = [line.removeprefix("tenant:").strip() for line in transcript.splitlines() if line.startswith("tenant:")]
    latest = turns[-1] if turns else transcript.strip()
    normalized = normalize_message(latest)
    normalized = re.sub(r"[,.!?]*\s+hey$", "", normalized)
    previous = " ".join(turns[:-1]).lower()

    def answer(reply: str, category: str = "other", urgency: str = "medium") -> Analysis:
        return Analysis(reply=reply, category=category, urgency=urgency,
                        summary=latest[:500] or "Tenant follow-up", likely_cause="Not established",
                        confidence=0.3, diy_appropriate=False, needs_follow_up=True)

    if normalized in {"hi", "hey", "hello", "good morning", "good afternoon"}:
        return answer("Hi! I'm here to help. What has happened in your unit?")
    if normalized in {"thanks", "thank you", "thank you hey", "okay", "ok"}:
        return answer("You're welcome. You can tell me more, or use the resolution button when the problem is sorted.")
    if normalized in {"i lost", "lost", "i have lost", "i lost my"}:
        return answer("What did you lose—your keys, access card, or something else?")
    if key_issue(latest) or normalized in {"keys", "the keys", "my keys", "unit keys", "my unit keys", "key", "the key", "my key", "access card", "my access card"}:
        return answer("Are you locked out right now, or are you safely inside? Don't force the door or lock. Your landlord or building manager can arrange authorised access.", "doors_locks", "high")
    key_context = any(word in previous for word in ("keys", "key", "locked out", "access card"))
    if key_context and normalized in {"yes", "yes i am", "outside", "im outside", "i'm outside", "i am outside", "i cant get in", "i can't get in", "locked out", "yes outside", "yes i am outside"}:
        return answer("Since you can't get inside, wait somewhere safe and contact your landlord or building manager for authorised access. Don't force the door. Is there a building manager or caretaker you can contact now?", "doors_locks", "high")
    if key_context and normalized in {"no", "no im inside", "no i'm inside", "inside", "i am inside", "i'm inside", "im inside"}:
        return answer("Good, you're inside. Don't leave without a way back in. Ask your landlord about a replacement key. Could the missing keys be linked to your address?", "doors_locks")
    if key_context and any(phrase in normalized for phrase in ("spare key", "spare", "caretaker", "building manager")):
        return answer("Ask the building manager or a trusted person who already holds an authorised spare. Your landlord can arrange a locksmith if there isn't one. Don't force the lock. Are you able to reach your landlord now?", "doors_locks", "high")
    if normalized in {"not fixed", "it is not fixed", "still not working", "no", "nope", "not yet", "it didn't work", "that didn't work"}:
        return answer("Thanks for trying. Don't repeat checks that didn't help or attempt repairs. " +
                      ("Your report is still open. What is happening now, and has anything become worse?" if escalated else
                       "What is happening now? You can also choose Report to landlord for help."))
    # Follow-up details should advance the conversation, not repeat the first checklist.
    if any(word in previous for word in ("tap", "water", "leak")):
        if "other taps" in normalized and any(phrase in normalized for phrase in ("no other", "none", "not working", "don't work", "do not work")):
            return answer("If the other taps also have no water, check with your building manager or neighbours about a supply interruption. Don't adjust unfamiliar valves. When did the water stop?", "plumbing")
        if any(phrase in normalized for phrase in ("other taps work", "only this tap", "just this tap", "only the kitchen", "only kitchen")):
            return answer("That helps narrow it to this tap or its supply. Don't remove the fittings. Is there any visible leak under the tap or sink?", "plumbing")
        if any(phrase in normalized for phrase in ("all taps", "none of the taps", "no taps", "whole unit", "both hot and cold", "both")):
            return answer("If the whole unit has no water, check with the building manager or neighbours about a supply interruption. Don't adjust unfamiliar valves. When did the water stop?", "plumbing")
        if any(phrase in normalized for phrase in ("under the sink", "under sink", "under the tap")):
            return answer("Keep the area under the sink clear and catch drips if safe. Don't touch nearby plugs or dismantle pipes. Is it a slow drip or a steady flow?", "plumbing")
        if any(phrase in normalized for phrase in ("this morning", "yesterday", "last night", "today")):
            return answer("Thanks, that tells me when it started. Is it affecting one fixture or the whole unit?", "plumbing")
    if normalized in {"[photo attached]", ""}:
        return answer("I've saved your photo, but local guidance can't inspect images. Please describe what it shows so I can help; you can also send the report to your landlord.")
    result = fallback_analysis(user_text=latest)
    if escalated:
        result.reply = result.reply.replace("The AI service is unavailable and I haven't sent this to your landlord. ", "")
    if result.category == "other":
        from .maintenance_classifier import predict
        learned = predict(latest)
        if learned and not learned['needs_review']:
            prompts = {
                'security': ("doors_locks", "Keep yourself somewhere safe and don't force a door or lock. Is this about missing keys, a damaged lock, or a window or gate that will not secure?"),
                'plumbing': ("plumbing", "Keep water away from electrical fittings and don't dismantle pipes. Is the problem a leak, a blockage, or no water coming through?"),
                'electrical': ("electrical", "Don't touch wiring, open electrical panels, or repeatedly reset a breaker. Is the power affected in one place or throughout the unit?"),
                'general': ("other", "Stop using the damaged fixture and keep the area clear. Which item is affected, and is it loose, broken, or not working?")}
            category, reply = prompts[learned['category']]
            return answer(reply, category, learned.get('suggested_priority', 'medium'))
    if result.category == "other" and previous:
        return answer("Thanks for the detail. What has changed since your last message, and where exactly is the problem? " +
                      ("This chat stays open while your landlord reviews the report." if escalated else "You can ask me a question or choose Report to landlord."))
    return result


def fallback_analysis(*, send_to_landlord: bool = False, user_text: str = "") -> Analysis:
    # Classify tenant text only; bot replies would otherwise bias every follow-up.
    tenant_lines = [line.split("tenant:", 1)[1] for line in user_text.splitlines() if line.startswith("tenant:")]
    issue_text = " ".join(tenant_lines) if tenant_lines else user_text
    normalized = " ".join(issue_text.lower().replace("’", "'").replace("'", "").split())
    if send_to_landlord:
        return Analysis(reply=f"I couldn't safely understand the assessment, so I sent this to your landlord for human review. {DISCLAIMER}",
                        category="other", urgency="medium", summary="Unable to classify; needs human review",
                        likely_cause="Unknown", confidence=0, diy_appropriate=False)
    
    # Check for specific scenarios with helpful responses
    if "tap" in normalized and any(term in normalized for term in ("no water", "cant get water", "not getting water", "take out water", "no water coming", "not giving water")):
        reply = (
            "I understand you have no water from the tap. Here are some safe checks:\n"
            "1. Check whether other taps have water in the unit.\n"
            "2. Note whether it's only hot water, cold water, or both.\n"
            "3. Check if it's load shedding or an area-wide issue.\n"
            "4. Don't remove the tap or its fittings. If you see a leak, keep water away from plugs and place a container underneath.\n\n"
            "Does another tap work, and is it hot water, cold water, or both? "
            f"{DISCLAIMER}"
        )
        return Analysis(reply=reply, category="plumbing", urgency="medium", summary="Tap has no water; cause not yet known",
                        likely_cause="Possible supply issue or tap fault", confidence=0.6, diy_appropriate=True,
                        suggested_steps=["Check other taps", "Identify whether hot, cold, or both supplies are affected", "Check for load shedding", "Do not remove tap fittings"],
                        needs_follow_up=True, follow_up_question="Does another tap work, and is it hot water, cold water, or both?")
    
    elif any(term in normalized for term in ("spare key", "need a key", "need keys", "locked out", "lost key", "lost keys", "lost my key", "lost my apartment keys", "stolen key", "stolen keys")):
        reply = (
            "Are you locked out right now? Could someone else have access to your keys or address? "
            "Please contact your landlord or building manager immediately. "
            "They can help with authorised access, a locksmith, or securing the property if needed. "
            "Don't force the door or lock."
        )
        return Analysis(reply=reply, category="doors_locks", urgency="high", summary="Lost or stolen keys reported",
                        likely_cause="Lost or stolen keys or lockout", confidence=0.85, diy_appropriate=False,
                        suggested_steps=["Contact landlord or building manager immediately", "Do not force the door or lock", "If in immediate danger, call emergency services"],
                        needs_follow_up=True, follow_up_question="Are you locked out right now, and could someone else have access to your keys?")
    
    elif any(term in normalized for term in ("geyser", "hot water", "no hot water", "cold shower")):
        reply = (
            "I understand you have a hot water issue. Here are some safe checks:\n"
            "1. Check if your geyser switch is on (usually in the distribution board).\n"
            "2. Do not open the geyser or touch its reset controls; ask your landlord to arrange a qualified technician.\n"
            "3. Check if it's an electricity supply issue (load shedding).\n"
            "4. Don't try to open or repair the geyser yourself.\n\n"
            "Is the geyser switch on, and do you have electricity? "
            f"{DISCLAIMER}"
        )
        return Analysis(reply=reply, category="appliance", urgency="medium", summary="Hot water/geyser issue",
                        likely_cause="Possible geyser fault or power issue", confidence=0.6, diy_appropriate=True,
                        suggested_steps=["Check geyser switch in distribution board", "Ask landlord for a qualified geyser technician", "Verify electricity supply", "Do not attempt geyser repairs"],
                        needs_follow_up=True, follow_up_question="Is the geyser switch on, and do you have electricity?")
    
    elif any(term in normalized for term in ("leak", "leaking", "dripping", "water leaking")):
        reply = (
            "I understand you have a leak. Here's what you can do safely:\n"
            "1. If safe, place a container or towels under the leak.\n"
            "2. Move belongings away from the water.\n"
            "3. Keep water away from electrical plugs and appliances.\n"
            "4. Only close a water valve if you know where it is and can reach it safely.\n"
            "5. Don't try to dismantle plumbing.\n\n"
            "Where is the leak coming from? "
            f"{DISCLAIMER}"
        )
        return Analysis(reply=reply, category="plumbing", urgency="medium", summary="Water leak reported",
                        likely_cause="Possible pipe or fixture fault", confidence=0.6, diy_appropriate=True,
                        suggested_steps=["Place container under leak", "Move belongings away", "Keep water away from electricity", "Close water valve if safe to do so"],
                        needs_follow_up=True, follow_up_question="Where is the leak coming from?")
    
    elif any(term in normalized for term in ("light", "bulb", "no light", "dark", "switch")):
        reply = (
            "I understand you have a lighting issue. Here are some safe checks:\n"
            "1. Check if it's load shedding.\n"
            "2. Try replacing the bulb with a working one.\n"
            "3. Check if the switch is working properly.\n"
            "4. Don't open light fittings or touch wiring.\n\n"
            "Is it affecting one light or the whole unit? "
            f"{DISCLAIMER}"
        )
        return Analysis(reply=reply, category="electrical", urgency="low", summary="Lighting issue reported",
                        likely_cause="Possible bulb fault or wiring issue", confidence=0.5, diy_appropriate=True,
                        suggested_steps=["Check for load shedding", "Try replacing the bulb", "Check the switch", "Do not touch wiring"],
                        needs_follow_up=True, follow_up_question="Is it affecting one light or the whole unit?")
    
    # Default fallback
    if send_to_landlord:
        reply = f"I couldn't safely understand the assessment, so I sent this to your landlord for human review. {DISCLAIMER}"
        summary = "Unable to classify; needs human review"
    else:
        reply = f"The AI service is unavailable and I haven't sent this to your landlord. I'm having trouble understanding the issue. Please describe what's wrong in more detail, attach a photo if possible, or choose 'Report to landlord' to send this directly to them. {DISCLAIMER}"
        summary = "AI service unavailable; awaiting tenant choice"
    
    return Analysis(reply=reply,
                    category="other", urgency="medium", summary=summary,
                    likely_cause="Unknown", confidence=0, diy_appropriate=False)


def analyze_with_ai(text: str, image_paths: list[str], *, escalated: bool = False) -> Analysis:
    """Assess text and private photos with Gemini; failures use the caller's local fallback."""
    import httpx

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
        raise ValueError("Invalid Gemini model name")
    parts: list[dict[str, Any]] = [{"text": text}]
    for path in image_paths:
        media = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[Path(path).suffix.lower()]
        parts.append({"inlineData": {"mimeType": media, "data": base64.b64encode(read_private_attachment(path)).decode("ascii")}})
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if escalated:
        system_prompt += (
            "\nThis request was already sent to the landlord. Use the newest detail and photos to keep helping. "
            "Offer relevant low-risk advice or one focused question. Do not repeat generic acknowledgements, "
            "claim the landlord has read it, promise a response time, or ask whether to send it again."
        )
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": Analysis.model_json_schema(),
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key}, json=payload,
        timeout=min(float(os.getenv("MAINTENANCE_AI_TIMEOUT_SECONDS", "12")), 15),
    )
    response.raise_for_status()
    try:
        candidates = response.json().get("candidates", [])
        if not candidates or candidates[0].get("finishReason") != "STOP":
            raise ValueError("Missing or incomplete Gemini assessment")
        raw = "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []) if not part.get("thought"))
        result = Analysis.model_validate_json(raw)
        if result.category not in m.CHAT_MAINTENANCE_CATEGORIES or result.urgency not in m.CHAT_MAINTENANCE_URGENCIES:
            raise ValueError("Unsupported assessment category or urgency")
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise AnalysisOutputError("Gemini returned an invalid or incomplete assessment") from exc
    # Electrical and structural topics are always referred to a human.
    if result.category == "electrical" or any(w in text.lower() for w in ("gas", "structural", "crack in the wall")):
        result.diy_appropriate = False
        result.suggested_steps = []
        if result.category == "electrical":
            result.reply = "Electrical problems can be dangerous. Please do not touch wiring or electrical equipment. I recommend your landlord or a qualified electrician assess it."
    result.reply = result.reply.strip()
    if DISCLAIMER.lower() not in result.reply.lower():
        result.reply = f"{result.reply} {DISCLAIMER}"
    if result.needs_follow_up and result.follow_up_question:
        result.reply += f"\n\n{result.follow_up_question}"
    elif result.diy_appropriate and not escalated:
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
