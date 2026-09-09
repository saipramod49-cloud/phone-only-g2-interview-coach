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
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as r:

            r.raise_for_status()

            async for line in r.aiter_lines():

                if not line.startswith("data: "):
                    continue

                data = line[6:]

                if data == "[DONE]":
                    break

                event = json.loads(data)

                if (
                    event.get("type")
                    == "response.output_text.delta"
                ):
                    yield event.get(
                        "delta",
                        "",
                    )


# ============================================================
# OPENAI REALTIME TRANSCRIPTION
# ============================================================

async def openai_transcription_session():

    key = os.environ["OPENAI_API_KEY"]

    # IMPORTANT:
    # This is a REALTIME session.
    #
    # The previous version connected to a realtime model but
    # tried to send:
    #
    #     "type": "transcription"
    #
    # which caused:
    #
    # "Passing a transcription session update to a realtime
    #  session is not allowed."
    #
    # So we keep this as a realtime session and enable
    # input transcription inside it.

    url = (
        "wss://api.openai.com/"
        "v1/realtime"
        "?model=gpt-realtime"
    )

    ws = await websockets.connect(
        url,
        additional_headers={
            "Authorization": f"Bearer {key}",
        },
        ping_interval=10,
        ping_timeout=10,
    )

    session_update = {
        "type": "session.update",
        "session": {

            # Must match the realtime transport above.
            "type": "realtime",

            # We do not need OpenAI speech output.
            "output_modalities": [
                "text"
            ],

            "audio": {
                "input": {

                    # main.py converts G2's 16 kHz PCM
                    # into 24 kHz PCM before sending here.
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },

                    "noise_reduction": {
                        "type": "far_field",
                    },

                    # Speech -> text only.
                    "transcription": {
                        "model": "gpt-4o-mini-transcribe",

                        "language": "en",

                        "prompt": (
                            "A professional job interview. "
                            "Preserve technical product names, "
                            "metrics, acronyms, company names, "
                            "cloud platform names, database names, "
                            "programming languages, data engineering "
                            "terminology, SQL terminology, GCP, Azure, "
                            "Snowflake, BigQuery, PySpark, Kafka, "
                            "Dataflow, Dataproc, and other technical "
                            "terms accurately."
                        ),
                    },

                    # Automatically detect when interviewer
                    # starts/stops speaking.
                    #
                    # main.py expects speech_started and a
                    # completed transcription event, so this
                    # is important.
                    "turn_detection": {
                        "type": "server_vad",

                        "threshold": 0.58,

                        "prefix_padding_ms": 300,

                        "silence_duration_ms": 650,

                        # We only want transcription here.
                        # answer_stream() creates our interview
                        # answer separately.
                        "create_response": False,
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
