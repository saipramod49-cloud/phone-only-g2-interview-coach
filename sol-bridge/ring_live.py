"""Server-owned GPT-Live microphone relay for the Ring Ask private beta."""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import time
from contextlib import suppress

import websockets
from fastapi import APIRouter, WebSocket

import ring_api

LIVE_URL = "wss://api.openai.com/v1/live/sessions"


def _next(iterator):
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


def router_for(credentials, answer_model):
    router = APIRouter()

    @router.websocket("/ws/ring-live")
    async def ring_live(ws: WebSocket):
        await ws.accept()
        upstream = None
        client_read = provider_read = None
        locked = False
        client_closed = False
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
            supplied = hello.get("token", "")
            expected = credentials["bridge_token"]
            if hello.get("type") != "auth" or not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
                await ws.close(code=1008, reason="Invalid bridge token")
                client_closed = True
                return

            upstream = await websockets.connect(
                LIVE_URL,
                additional_headers={"Authorization": "Bearer " + credentials["api_key"]},
                ping_interval=10,
                ping_timeout=10,
                close_timeout=5,
            )
            await upstream.send(json.dumps({
                "type": "session.start",
                "event_id": "ring_start",
                "session": {
                    "model": "gpt-live-1",
                    "instructions": (
                        "Listen carefully and preserve the user's exact technical wording. "
                        "Do not speak. Delegate each completed request to the client."
                    ),
                    "audio": {
                        "format": {"type": "audio/pcm", "rate": 16000},
                        "output": {"voice": "marin"},
                    },
                    "delegation": {"type": "client"},
                },
            }))
            while True:
                event = json.loads(await asyncio.wait_for(upstream.recv(), timeout=15))
                if event.get("type") == "session.started":
                    break
                if event.get("type") == "error":
                    raise RuntimeError("GPT Live rejected session setup")
            await ws.send_json({"type": "ready", "model": "gpt-live-1"})

            transcript = ""
            finish_at = last_delta = None
            instructions = ""
            client_read = asyncio.create_task(ws.receive())
            provider_read = asyncio.create_task(upstream.recv())
            while True:
                now = time.monotonic()
                if finish_at is not None:
                    quiet_from = max(finish_at, last_delta or finish_at)
                    if transcript.strip() and now - quiet_from >= 1.0:
                        break
                    if now - finish_at >= 6.0:
                        raise ValueError("No speech detected")
                done, _ = await asyncio.wait(
                    (client_read, provider_read),
                    timeout=0.20,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if client_read in done:
                    message = client_read.result()
                    if message["type"] == "websocket.disconnect":
                        return
                    audio = message.get("bytes")
                    if audio is not None:
                        if finish_at is None and audio:
                            if len(audio) > 64000 or len(audio) % 2:
                                await ws.close(code=1009, reason="Invalid PCM frame")
                                return
                            await upstream.send(json.dumps({
                                "type": "session.input_audio.append",
                                "audio": base64.b64encode(audio).decode("ascii"),
                            }))
                    else:
                        command = json.loads(message.get("text") or "{}")
                        if command.get("type") == "cancel":
                            return
                        if command.get("type") == "finish" and finish_at is None:
                            value = command.get("instructions", "")
                            if not isinstance(value, str) or len(value) > 800:
                                raise ValueError("Invalid answer instructions")
                            instructions = value.strip()
                            finish_at = time.monotonic()
                            # Supply one second of silence so Live can finish the last
                            # transcript segment after the glasses microphone stops.
                            await upstream.send(json.dumps({
                                "type": "session.input_audio.append",
                                "audio": base64.b64encode(b"\0" * 32000).decode("ascii"),
                            }))
                            await ws.send_json({"type": "status", "text": "Finishing GPT Live transcript…"})
                    client_read = asyncio.create_task(ws.receive())
                if provider_read in done:
                    event = json.loads(provider_read.result())
                    kind = event.get("type", "")
                    if kind == "session.input_transcript.delta":
                        delta = event.get("delta", "")
                        if isinstance(delta, str) and delta:
                            transcript += delta
                            last_delta = time.monotonic()
                            await ws.send_json({"type": "transcript.partial", "text": transcript.strip()})
                    elif kind == "error":
                        raise RuntimeError("GPT Live session failed")
                    elif kind == "session.closed" and finish_at is None:
                        raise RuntimeError("GPT Live session closed")
                    provider_read = asyncio.create_task(upstream.recv())

            question = transcript.strip()
            await ws.send_json({
                "type": "transcript",
                "text": question,
                "transcriptionMs": round((time.monotonic() - finish_at) * 1000),
                "source": "gpt-live-1",
            })
            if not ring_api._busy.acquire(blocking=False):
                await ws.send_json({"type": "error", "text": "A question is already processing."})
                return
            locked = True
            iterator = ring_api.ring_agent.conversation.stream(
                question, answer_model, credentials["api_key"], "natural", instructions
            )
            while True:
                available, item = await asyncio.to_thread(_next, iterator)
                if not available:
                    break
                if item.get("type") == "done":
                    item = {**item, "transport": "gpt-live-1"}
                await ws.send_json(item)
                if item.get("type") in ("done", "error"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            with suppress(Exception):
                await ws.send_json({"type": "error", "text": "GPT Live was unavailable; using the recorded-audio fallback."})
        finally:
            if locked:
                ring_api._busy.release()
            for task in (client_read, provider_read):
                if task:
                    task.cancel()
            if client_read or provider_read:
                await asyncio.gather(*(task for task in (client_read, provider_read) if task), return_exceptions=True)
            if upstream:
                with suppress(Exception):
                    await upstream.send(json.dumps({"type": "session.close"}))
                with suppress(Exception):
                    await upstream.close()
            if not client_closed:
                with suppress(Exception):
                    await ws.close()

    return router
