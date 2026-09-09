from __future__ import annotations

import json
import os

import httpx
import websockets


SYSTEM = """
You are answering an interview question as the candidate.

Use only grounded facts in CANDIDATE EVIDENCE.
Never invent employers, dates, metrics, tools, responsibilities,
projects, or outcomes.

Answer in first person, directly and naturally.

Prefer 3-5 compact lines suitable for smart glasses.

Lead with the answer, then the strongest concrete example.

Use labels such as ACTION: and RESULT: only when helpful.

Bold at most 4 critical phrases with **double asterisks**;
the client converts them to supported emphasis.

If evidence is insufficient, say what you genuinely can say
without fabricating.

Do not coach or explain how to answer.
"""


# ============================================================
# ANSWER GENERATION
# ============================================================

async def answer_stream(
    question: str,
    evidence: str,
):

    key = os.environ["OPENAI_API_KEY"]

    payload = {
        "model": os.getenv(
            "OPENAI_MODEL",
            "gpt-5-mini",
        ),
        "stream": True,
        "input": [
            {
                "role": "system",
                "content": SYSTEM,
            },
            {
                "role": "user",
                "content": (
                    f"QUESTION:\n"
                    f"{question}\n\n"
                    f"CANDIDATE EVIDENCE:\n"
                    f"{evidence}"
                ),
            },
        ],
        "max_output_tokens": 260,
    }

    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        async with client.stream(
            "POST",
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization":
                    f"Bearer {key}",
                "Content-Type":
                    "application/json",
            },
            json=payload,
        ) as r:

            r.raise_for_status()

            async for line in r.aiter_lines():

                if not line.startswith(
                    "data: "
                ):
                    continue

                data = line[6:]

                if data == "[DONE]":
                    break

                event = json.loads(data)

                if (
                    event.get("type")
                    ==
                    "response.output_text.delta"
                ):

                    yield event.get(
                        "delta",
                        "",
                    )


# ============================================================
# REALTIME TRANSCRIPTION
# ============================================================

async def openai_transcription_session():

    key = os.environ["OPENAI_API_KEY"]

    # Realtime transport model.
    url = (
        "wss://api.openai.com/"
        "v1/realtime"
        "?model=gpt-realtime"
    )

    ws = await websockets.connect(
        url,
        additional_headers={
            "Authorization":
                f"Bearer {key}",
        },
        ping_interval=10,
        ping_timeout=10,
    )

    # IMPORTANT:
    #
    # gpt-live-transcribe is used as the transcription model.
    #
    # DO NOT add:
    #
    # "turn_detection": {...}
    #
    # because the API is currently rejecting turn detection
    # for this transcription model.

    session_update = {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {

                    "format": {
                        "type":
                            "audio/pcm",
                        "rate":
                            24000,
                    },

                    "noise_reduction": {
                        "type":
                            "far_field",
                    },

                    "transcription": {
                        "model":
                            "gpt-live-transcribe",

                        "languages": [
                            "en"
                        ],

                        "delay":
                            "low",

                        "prompt": (
                            "A professional job interview. "
                            "Preserve technical product names, "
                            "metrics, acronyms, company names, "
                            "cloud platform names, database names, "
                            "and engineering terminology."
                        ),
                    },
                }
            },
        },
    }

    await ws.send(
        json.dumps(
            session_update
        )
    )

    return ws
