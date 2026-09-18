"""Ring Ask endpoint reusing the existing authenticated Live handler."""
import os

from fastapi import APIRouter, WebSocket

router = APIRouter()


def live_enabled() -> bool:
    return os.getenv("OPENAI_LIVE_EXPERIMENT", "0") == "1"


@router.get("/api/ring-live/status")
async def ring_live_status():
    # This checks routing only; it does not contact OpenAI.
    return {
        "route": "/ws/ring-live",
        "enabled": live_enabled(),
        "check": "routing_only",
    }


@router.websocket("/ws/ring-live")
async def ring_live(ws: WebSocket):
    if not live_enabled():
        await ws.close(code=1008, reason="Live experiment is disabled")
        return

    # Delegate authentication, microphone control and answer events.
    # The existing handler accepts this socket and requires APP_TOKEN.
    from .live_gpt import live as existing_live_handler

    print("RING_LIVE_CONNECT", flush=True)
    await existing_live_handler(ws)
