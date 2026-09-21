"""Ephemeral remote-phone audio relay for live captions on Ring Ask."""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .providers import openai_caption_session, transcription_diagnostic

router = APIRouter()
SENDER_PAGE = Path(__file__).with_name("remote_sender.html")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_AUDIO_FRAME = 96 * 1024
MAX_CAPTION_CHARS = 1800


@dataclass
class CaptionSession:
    receiver: WebSocket
    expires_at: float
    sender: WebSocket | None = None
    final_lines: list[str] = field(default_factory=list)


sessions: dict[str, CaptionSession] = {}
sessions_lock = asyncio.Lock()


def _authorized(token: str) -> bool:
    expected = (os.getenv("APP_TOKEN", ""), os.getenv("BRIDGE_TOKEN", ""))
    return bool(token) and any(value and hmac.compare_digest(token, value) for value in expected)


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def _normalise_code(value: str) -> str:
    raw = "".join(character for character in value.upper() if character in ALPHABET)
    return raw[:4] + "-" + raw[4:] if len(raw) == 8 else ""


async def _safe_send(ws: WebSocket | None, payload: dict):
    if ws is not None:
        with suppress(Exception):
            await ws.send_json(payload)


async def _caption_reader(openai_ws, session: CaptionSession):
    partials: dict[str, str] = {}
    async for raw in openai_ws:
        event = json.loads(raw)
        kind = event.get("type", "")
        if kind == "conversation.item.input_audio_transcription.delta":
            item = str(event.get("item_id", "current"))
            partials[item] = (partials.get(item, "") + str(event.get("delta", "")))[-MAX_CAPTION_CHARS:]
            text = (" ".join(session.final_lines) + " " + partials[item]).strip()[-MAX_CAPTION_CHARS:]
            await _safe_send(session.receiver, {"type": "caption.partial", "text": text})
            await _safe_send(session.sender, {"type": "caption.partial", "text": text})
        elif kind == "conversation.item.input_audio_transcription.completed":
            item = str(event.get("item_id", "current"))
            text = str(event.get("transcript") or partials.pop(item, "")).strip()
            if text:
                session.final_lines.append(text)
                while len(" ".join(session.final_lines)) > MAX_CAPTION_CHARS and len(session.final_lines) > 1:
                    session.final_lines.pop(0)
                combined = " ".join(session.final_lines)[-MAX_CAPTION_CHARS:]
                await _safe_send(session.receiver, {"type": "caption.final", "text": combined})
                await _safe_send(session.sender, {"type": "caption.final", "text": combined})
        elif kind == "error":
            raise RuntimeError("OpenAI caption stream failed")


@router.get("/remote-captions/")
async def remote_caption_sender_page():
    return FileResponse(SENDER_PAGE, headers={"Cache-Control": "no-store"})


@router.websocket("/ws/remote-captions/receive")
async def remote_caption_receiver(ws: WebSocket):
    await ws.accept()
    code = ""
    try:
        auth = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if auth.get("type") != "auth" or not _authorized(str(auth.get("token", ""))):
            await ws.close(code=4401, reason="Invalid app access token")
            return
        lifetime = max(300, min(int(os.getenv("REMOTE_CAPTION_SESSION_SECONDS", "3600")), 14400))
        async with sessions_lock:
            for _ in range(20):
                candidate = _new_code()
                if candidate not in sessions:
                    code = candidate
                    break
            if not code:
                await ws.close(code=1013, reason="Could not allocate session")
                return
            sessions[code] = CaptionSession(ws, time.monotonic() + lifetime)
        scheme = "https" if ws.url.scheme == "wss" else "http"
        sender_url = f"{scheme}://{ws.url.netloc}/remote-captions/?code={code}"
        await ws.send_json({"type": "session", "code": code, "sender_url": sender_url, "expires_in": lifetime})
        while True:
            message = await ws.receive_json()
            if message.get("type") == "stop":
                break
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        async with sessions_lock:
            session = sessions.pop(code, None) if code else None
        if session and session.sender:
            with suppress(Exception):
                await session.sender.close(code=1000, reason="Caption receiver stopped")


@router.websocket("/ws/remote-captions/send/{raw_code}")
async def remote_caption_sender(ws: WebSocket, raw_code: str):
    await ws.accept()
    code = _normalise_code(raw_code)
    async with sessions_lock:
        session = sessions.get(code)
        if not session or session.expires_at <= time.monotonic() or session.sender is not None:
            session = None
        else:
            session.sender = ws
    if not session:
        await ws.close(code=4404, reason="Session unavailable or expired")
        return
    openai_ws = None
    reader = None
    try:
        openai_ws = await openai_caption_session()
        reader = asyncio.create_task(_caption_reader(openai_ws, session))
        await _safe_send(session.receiver, {"type": "sender.connected"})
        await _safe_send(ws, {"type": "ready"})
        while time.monotonic() < session.expires_at:
            receive_task = asyncio.create_task(ws.receive())
            done, _ = await asyncio.wait(
                {receive_task, reader},
                timeout=max(0, session.expires_at - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                receive_task.cancel()
                break
            if reader in done:
                receive_task.cancel()
                await reader
                break
            message = receive_task.result()
            if message.get("type") == "websocket.disconnect":
                break
            audio = message.get("bytes")
            if audio is not None:
                if len(audio) > MAX_AUDIO_FRAME:
                    await ws.close(code=1009, reason="Audio frame too large")
                    break
                await openai_ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(audio).decode("ascii")}))
            elif message.get("text"):
                command = json.loads(message["text"])
                if command.get("type") == "stop":
                    break
        if time.monotonic() >= session.expires_at:
            await _safe_send(session.receiver, {"type": "expired"})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as error:
        print("REMOTE_CAPTION_FAILED " + transcription_diagnostic(error), flush=True)
        await _safe_send(session.receiver, {"type": "error", "text": "Remote transcription stopped. Start a new session and try again."})
        await _safe_send(ws, {"type": "error", "text": "Transcription service unavailable."})
    finally:
        if reader:
            reader.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await reader
        if openai_ws:
            with suppress(Exception):
                await openai_ws.close()
        async with sessions_lock:
            if sessions.get(code) is session:
                session.sender = None
        await _safe_send(session.receiver, {"type": "sender.disconnected"})
