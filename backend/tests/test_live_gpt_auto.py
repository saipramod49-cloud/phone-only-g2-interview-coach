import asyncio
import json

from fastapi.testclient import TestClient

from app import live_gpt, storage
from app.main import app


def test_live_backend_dossier_includes_active_profile_material(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DB", tmp_path / "auto.sqlite3")
    monkeypatch.setattr(live_gpt, "connect", storage.connect)

    with storage.connect() as db:
        profile = storage.active_profile(db)
        db.execute(
            "UPDATE profiles SET name=?, job_description=? WHERE id=?",
            ("Data Engineer", "Build reliable BigQuery pipelines.", profile["id"]),
        )
        db.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?)",
            (
                "resume-1",
                profile["id"],
                "Resume",
                "resume",
                "Built Airflow orchestration and Kafka ingestion.",
                1.0,
            ),
        )
        db.commit()

    prompt = live_gpt.backend_instructions("Keep answers conversational.")
    assert "Build reliable BigQuery pipelines" in prompt
    assert "Built Airflow orchestration and Kafka ingestion" in prompt
    assert "Keep answers conversational" in prompt


def test_target_platform_prioritizes_jd_and_hypothetical_scenarios_are_honest(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DB", tmp_path / "azure.sqlite3")
    monkeypatch.setattr(live_gpt, "connect", storage.connect)
    with storage.connect() as db:
        profile = storage.active_profile(db)
        db.execute(
            "UPDATE profiles SET job_description=? WHERE id=?",
            ("Azure Data Engineer using ADF, ADLS Gen2, Synapse and Databricks", profile["id"]),
        )
        db.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?)",
            ("resume-gcp", profile["id"], "Resume", "resume", "Historical BigQuery and GCS project.", 1.0),
        )
        db.commit()
    prompt = live_gpt.backend_instructions()
    assert "TARGET PLATFORM: AZURE" in prompt
    assert "Historical BigQuery and GCS project" in prompt
    assert "Never silently swap" in prompt
    assert 'framed honestly as "I would"' in prompt
    assert live_gpt.target_platform("BigQuery, GCS and Composer") == "GCP"
    assert live_gpt.target_platform("S3, Glue and Redshift") == "AWS"


def test_live_prompt_rejects_non_directed_and_candidate_speech():
    assert "directed to the wearer" in live_gpt.LIVE_INSTRUCTIONS
    assert "wearer's own spoken answer" in live_gpt.LIVE_INSTRUCTIONS


class FakeLiveConnection:
    def __init__(self):
        self.events = []
        self.closed = False
        self.emitted = False

    async def send(self, raw):
        event = json.loads(raw)
        if event.get("type") == "session.input_audio.append" and not self.emitted:
            self.emitted = True
            self.events.extend(
                [
                    {"type": "session.input_transcript.delta", "delta": "Explain Kafka lag?", "end_ms": 100},
                    {
                        "type": "session.delegation.created",
                        "offset_ms": 100,
                        "delegation": {"id": "d1", "target": "responses"},
                    },
                    {
                        "type": "response.event",
                        "delegation_id": "d1",
                        "event": {"type": "response.output_text.delta", "delta": "I would inspect consumer lag."},
                    },
                    {
                        "type": "response.event",
                        "delegation_id": "d1",
                        "event": {"type": "response.completed"},
                    },
                ]
            )

    def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.events and not self.closed:
            await asyncio.sleep(0.001)
        if self.closed:
            raise StopAsyncIteration
        return json.dumps(self.events.pop(0))

    async def close(self):
        self.closed = True


def test_auto_conversation_rearms_same_live_session(monkeypatch):
    fake = FakeLiveConnection()

    async def open_session(_instructions=""):
        return fake

    monkeypatch.setenv("APP_TOKEN", "test-token")
    monkeypatch.setenv("OPENAI_LIVE_EXPERIMENT", "1")
    monkeypatch.setattr(live_gpt, "open_gpt_live_session", open_session)

    with TestClient(app) as client, client.websocket_connect("/ws/ring-live") as ws:
        ws.send_json({"type": "auth", "token": "test-token"})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "conversation.mode", "active": True})
        assert ws.receive_json() == {"type": "conversation.mode", "active": True}
        ws.send_json({"type": "listen"})

        while ws.receive_json().get("type") != "capture":
            pass

        ws.send_bytes(b"\0\0" * 320)
        events = []
        for _ in range(20):
            event = ws.receive_json()
            events.append(event)
            if event.get("type") == "capture" and event.get("active") is True and any(
                item.get("type") == "answer.done" for item in events
            ):
                break

    assert any(event.get("type") == "answer.done" for event in events)
    assert events[-1] == {"type": "capture", "active": True}
    assert not fake.closed or fake.emitted
