import asyncio
import base64
import json

import httpx
import pytest
from app.routers.maintenance import _analyze_with_deadline
from app.services import maintenance_chat as chat


def assessment(**changes):
    data = dict(reply="The round shape is blue.", category="other", urgency="low", summary="Test photo", likely_cause="Not established", confidence=0.4, diy_appropriate=False, suggested_steps=[], needs_follow_up=False, follow_up_question=None)
    return dict(data, **changes)


def test_gemini_sends_text_images_and_validates_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-private-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(chat, "read_private_attachment", lambda path: b"test-image-bytes")
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(assessment())}]}}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    result = chat.analyze_with_ai("Check the earlier picture", ["private/photo.png"], escalated=True)
    url, args = calls[0]
    assert "gemini-3.8-flash:generateContent" in url
    assert "test-private-key" not in url
    assert args["headers"]["x-goog-api-key"] == "test-private-key"
    parts = args["json"]["contents"][0]["parts"]
    assert parts[0]["text"] == "Check the earlier picture"
    assert parts[1]["text"] == "Photo 1:"
    assert base64.b64decode(parts[2]["inlineData"]["data"]) == b"test-image-bytes"
    assert parts[2]["inlineData"]["mimeType"] == "image/png"
    assert "already sent" in args["json"]["systemInstruction"]["parts"][0]["text"]
    assert args["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "blue" in result.reply


@pytest.mark.parametrize("candidate", [
    {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}},
    {"finishReason": "STOP", "content": {"parts": [{"text": "invalid json"}]}},
    {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(assessment(category="invalid"))}]}},
])
def test_gemini_rejects_incomplete_or_invalid_assessments(monkeypatch, candidate):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(200, json={"candidates": [candidate]}, request=httpx.Request("POST", url)))
    with pytest.raises(chat.AnalysisOutputError):
        chat.analyze_with_ai("A fixture is broken", [])


def test_gemini_key_required_and_quota_errors_propagate(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        chat.analyze_with_ai("Hello", [])
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}, request=httpx.Request("POST", url)))
    with pytest.raises(httpx.HTTPStatusError):
        chat.analyze_with_ai("Hello", [])


def test_configured_gemini_handles_text_chat_by_default(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("LANDKEEP_LOCAL_COMPLAINTS", raising=False)
    expected = chat.Analysis(**assessment(reply="Where is the tap dripping from?"))
    monkeypatch.setattr(chat, "analyze_with_ai", lambda text, paths: expected)

    result = asyncio.run(_analyze_with_deadline("tenant: My kitchen tap is leaking", []))

    assert result is expected
