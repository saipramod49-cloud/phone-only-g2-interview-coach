import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import ring_live


class Client:
    def __init__(self, token="test"):
        self.token = token
        self.messages = [
            {"type": "websocket.receive", "bytes": b"\0" * 6400},
            {"type": "websocket.receive", "text": json.dumps({"type": "finish", "instructions": "Be brief"})},
        ]
        self.sent = []
        self.closed = None

    async def accept(self): pass
    async def receive_json(self): return {"type": "auth", "token": self.token}
    async def receive(self):
        if self.messages: return self.messages.pop(0)
        await asyncio.Event().wait()
    async def send_json(self, value): self.sent.append(value)
    async def close(self, code=1000, reason=""): self.closed = (code, reason)


class Provider:
    def __init__(self):
        self.events = [
            {"type": "session.started", "session": {"id": "live_test"}},
            {"type": "session.input_transcript.delta", "delta": "What is Kafka?"},
        ]
        self.sent = []
        self.closed = False

    async def send(self, value): self.sent.append(json.loads(value))
    async def recv(self):
        if self.events: return json.dumps(self.events.pop(0))
        await asyncio.Event().wait()
    async def close(self): self.closed = True


class LiveRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_audio_through_live_then_uses_existing_answer_agent(self):
        provider = Provider()
        connect = AsyncMock(return_value=provider)
        router = ring_live.router_for({"bridge_token": "test", "api_key": "fake"}, "gpt-6-astra")
        endpoint = router.routes[0].endpoint
        client = Client()
        answer = iter([{"type": "delta", "text": "Kafka is a distributed log."}, {"type": "done", "model": "gpt-5.6-sol"}])
        with patch.object(ring_live.websockets, "connect", connect), patch.object(ring_live.ring_api.ring_agent.conversation, "stream", return_value=answer) as stream:
            await asyncio.wait_for(endpoint(client), timeout=3)
        self.assertEqual(client.sent[0]["type"], "ready")
        self.assertIn("transcript.partial", [event["type"] for event in client.sent])
        self.assertIn("transcript", [event["type"] for event in client.sent])
        self.assertEqual(client.sent[-1]["type"], "done")
        self.assertEqual(client.sent[-1]["transport"], "gpt-live-1")
        stream.assert_called_once_with("What is Kafka?", "gpt-6-astra", "fake", "natural", "Be brief")
        audio = [event for event in provider.sent if event["type"] == "session.input_audio.append"]
        self.assertEqual(len(audio), 2)
        self.assertEqual(provider.sent[0]["type"], "session.start")
        self.assertEqual(provider.sent[0]["session"]["audio"]["format"]["rate"], 16000)
        self.assertTrue(provider.closed)

    async def test_rejects_bad_token_before_opening_billable_live_session(self):
        router = ring_live.router_for({"bridge_token": "test", "api_key": "fake"}, "gpt-6-astra")
        client = Client(token="wrong")
        with patch.object(ring_live.websockets, "connect", AsyncMock()) as connect:
            await router.routes[0].endpoint(client)
        connect.assert_not_awaited()
        self.assertEqual(client.closed[0], 1008)


if __name__ == "__main__": unittest.main()
