import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_ring_ask_health_static_page_and_auth(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("OPENAI_LIVE_EXPERIMENT", "1")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        health = client.get("/api/health", headers={"Authorization": "Bearer test-token"})
        assert health.status_code == 200
        assert health.json()["live_model"] == "gpt-live-1"
        page = client.get("/ring/")
        assert page.status_code == 200
        assert "v0.9.0 AUTO CONVERSATION" in page.text
        assert client.get("/ring/../main.py").status_code == 404


def test_ring_ask_batch_fallback_streams_existing_answer_format(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")

    async def transcribe(_pcm): return "What is Kafka?"
    async def answer(*_args, **_kwargs):
        yield "Kafka is "
        yield "a distributed log."

    with patch("app.ring_ask._transcribe", transcribe), patch("app.ring_ask._evidence", return_value=""), patch("app.ring_ask.answer_stream", answer), TestClient(app) as client:
        response = client.post(
            "/api/ask",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/octet-stream",
                "X-Answer-Instructions": "Be%20brief",
            },
            content=b"\0" * 6400,
        )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["status", "transcript", "delta", "delta", "done"]
    assert events[1]["text"] == "What is Kafka?"
    assert events[-1]["transport"] == "batch-fallback"
