"""Ring Ask HTTP compatibility routes for the deployed Interview Lens service."""
from __future__ import annotations

import io
import json
import hmac
import os
import time
import urllib.parse
import wave
from collections import deque
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .providers import answer_stream
from .retrieval import search_live
from .storage import active_profile, chunks_for, connect, core_profile_for

router = APIRouter()
ROOT = Path(__file__).with_name("ring_ui")
history = deque(maxlen=8)


def _authorized(authorization: str | None) -> bool:
    supplied = authorization[7:] if isinstance(authorization, str) and authorization.startswith("Bearer ") else ""
    expected = [os.getenv("APP_TOKEN", ""), os.getenv("BRIDGE_TOKEN", "")]
    return bool(supplied) and any(value and hmac.compare_digest(supplied, value) for value in expected)


def _require_auth(authorization: str | None):
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Invalid app access token")


def _wav(pcm: bytes) -> bytes:
    if not 6400 <= len(pcm) <= 9600000 or len(pcm) % 2:
        raise HTTPException(status_code=400, detail="Record between 0.2 and 300 seconds.")
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
        writer.writeframes(pcm)
    return output.getvalue()


async def _transcribe(pcm: bytes) -> str:
    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
            data={"model": model},
            files={"file": ("question.wav", _wav(pcm), "audio/wav")},
        )
    if response.status_code >= 400:
        raise RuntimeError("OpenAI transcription failed")
    text = response.json().get("text", "").strip()
    if not text:
        raise ValueError("No speech detected")
    return text


def _evidence(question: str) -> str:
    with connect() as db:
        profile = active_profile(db)
        if not profile:
            return ""
        chunks = chunks_for(db, profile["id"], include_core=False)
        core = core_profile_for(db, profile["id"])
    matches = search_live(chunks, question)
    return ("[USER-REPORTED CORE PROFILE]\n" + core + "\n\n" if core else "") + "\n\n".join(
        f"[{chunk.source}] {chunk.text}" for chunk in matches
    )


@router.get("/api/health")
async def health(authorization: str | None = Header(None)):
    _require_auth(authorization)
    return {
        "configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_LIVE_BACKEND_MODEL", "gpt-5.6-terra"),
        "live_model": os.getenv("OPENAI_LIVE_MODEL", "gpt-live-1"),
        "live_transport": os.getenv("OPENAI_LIVE_EXPERIMENT", "0") == "1",
        "reasoning": "delegated",
        "version": "0.11.0",
        "max_recording_seconds": 300,
    }


@router.post("/api/ask")
async def ask(
    request: Request,
    authorization: str | None = Header(None),
    x_answer_instructions: str = Header(""),
):
    _require_auth(authorization)
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise HTTPException(status_code=415, detail="Expected PCM audio.")
    pcm = await request.body()
    if len(pcm) > 9600000:
        raise HTTPException(status_code=413, detail="Recording is too large.")
    instructions = urllib.parse.unquote(x_answer_instructions)[:800].replace("\r", " ").replace("\n", " ")

    async def events():
        started = time.perf_counter()
        try:
            yield json.dumps({"type": "status", "text": "Transcribing question…"}) + "\n"
            question = await _transcribe(pcm)
            yield json.dumps({"type": "transcript", "text": question, "transcriptionMs": round((time.perf_counter() - started) * 1000)}) + "\n"
            answer = ""
            context = "\n".join(history)[-16000:]
            model = os.getenv("RING_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5-mini")
            async for delta in answer_stream(question, _evidence(question), context, "english", model, "low", instructions):
                answer += delta
                yield json.dumps({"type": "delta", "text": delta}) + "\n"
            history.extend(("user: " + question, "assistant: " + answer))
            yield json.dumps({"type": "done", "model": model, "transport": "batch-fallback"}) + "\n"
        except Exception:
            yield json.dumps({"type": "error", "text": "Could not complete the answer. Check the connection and try again."}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/ring/{asset_path:path}")
async def ring_ui(asset_path: str = ""):
    target = (ROOT / (asset_path or "index.html")).resolve()
    if ROOT.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target, headers={"Cache-Control": "no-cache"})
