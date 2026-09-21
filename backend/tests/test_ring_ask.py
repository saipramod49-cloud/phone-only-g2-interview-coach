import asyncio
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
        assert health.json()["version"] == "0.11.0"
        assert "v0.11.0 REMOTE CAPTIONS" in page.text
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


def test_remote_caption_page_and_authenticated_receiver(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token")
    with TestClient(app) as client:
        page = client.get("/remote-captions/")
        assert page.status_code == 200
        assert "I confirm everyone" in page.text
        with client.websocket_connect("/ws/remote-captions/receive") as ws:
            ws.send_json({"type": "auth", "token": "test-token"})
            session = ws.receive_json()
            assert session["type"] == "session"
            assert len(session["code"]) == 9
            assert session["sender_url"].endswith("?code=" + session["code"])
            ws.send_json({"type": "stop"})


def test_remote_caption_receiver_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/remote-captions/receive") as ws:
            ws.send_json({"type": "auth", "token": "wrong"})
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message["code"] == 4401


def test_remote_audio_is_relayed_as_partial_and_final_captions(monkeypatch):
    monkeypatch.setenv("APP_TOKEN", "test-token")

    class FakeOpenAI:
        def __init__(self):
            self.events = asyncio.Queue()

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.events.get()

        async def send(self, raw):
            if json.loads(raw)["type"] == "input_audio_buffer.append":
                await self.events.put(json.dumps({"type": "conversation.item.input_audio_transcription.delta", "item_id": "one", "delta": "Hello lens"}))
                await self.events.put(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "item_id": "one", "transcript": "Hello lens"}))

        async def close(self):
            return None

    async def open_fake():
        return FakeOpenAI()

    with patch("app.remote_captions.openai_caption_session", open_fake), TestClient(app) as client:
        with client.websocket_connect("/ws/remote-captions/receive") as receiver:
            receiver.send_json({"type": "auth", "token": "test-token"})
            session = receiver.receive_json()
            with client.websocket_connect("/ws/remote-captions/send/" + session["code"]) as sender:
                assert receiver.receive_json()["type"] == "sender.connected"
                assert sender.receive_json()["type"] == "ready"
                sender.send_bytes(b"\0\0" * 1200)
                assert receiver.receive_json() == {"type": "caption.partial", "text": "Hello lens"}
                assert receiver.receive_json() == {"type": "caption.final", "text": "Hello lens"}
                sender.send_json({"type": "stop"})
            receiver.send_json({"type": "stop"})
