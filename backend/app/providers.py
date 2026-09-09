from __future__ import annotations

import json
import os

import httpx
import websockets


SYSTEM = """
You are answering a technical job interview question as the candidate.

Use only facts supported by CANDIDATE EVIDENCE.
Never invent employers, dates, metrics, responsibilities,
projects, tools, technologies, or outcomes.

Answer in first person.

Give the direct answer immediately.
Keep the answer concise and natural for speaking in an interview.

Preferred structure:
1. Direct answer
2. Brief technical explanation
3. One relevant example from my experience only if evidence supports it

Target approximately 3 to 5 short lines.
Avoid introductions such as "Sure" or "Certainly".
Avoid coaching language.
Avoid saying "based on the provided evidence".

If the question is general technical knowledge and does not
require personal experience, answer the technical question directly.

If personal experience is required but the evidence is insufficient,
say only what can truthfully be supported.
""".strip()


# ============================================================
# ANSWER GENERATION
# ============================================================

async def answer_stream(
    question: str,
    evidence: str,
):
    key = os.environ["OPENAI_API_KEY"]

    model = os.getenv(
        "OPENAI_MODEL",
        "gpt-5.6-luna",
    )

    payload = {
        "model": model,

        # Disable reasoning for interview-speed responses.
        "reasoning": {
            "effort": "none",
        },

        "stream": True,

        "input": [
            {
                "role": "system",
                "content": SYSTEM,
            },
            {
                "role": "user",
                "content": (
                    "QUESTION:\n"
                    f"{question}\n\n"
                    "CANDIDATE EVIDENCE:\n"
                    f"{evidence}"
                ),
            },
        ],

        # Smart-glasses answer should stay short.
        "max_output_tokens": 180,
    }

    timeout = httpx.Timeout(
        connect=10.0,
        read=30.0,
        write=10.0,
        pool=10.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout
    ) as client:

        async with client.stream(
            "POST",
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as response:

            response.raise_for_status()

            async for line in response.aiter_lines():

                if not line.startswith("data: "):
                    continue

                data = line[6:]

                if data == "[DONE]":
                    break

                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if (
                    event_type
                    == "response.output_text.delta"
                ):
                    delta = event.get(
                        "delta",
                        "",
                    )

                    if delta:
                        yield delta


# ============================================================
# OPENAI REALTIME TRANSCRIPTION
# ============================================================

async def openai_transcription_session():

    key = os.environ["OPENAI_API_KEY"]

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

        # Keep OpenAI websocket healthy.
        ping_interval=10,
        ping_timeout=10,

        # Prevent unnecessary connection closure
        # during short network delays.
        close_timeout=5,
    )

    session_update = {
        "type": "session.update",

        "session": {

            # We are using a normal realtime session
            # with input transcription enabled.
            "type": "realtime",

            # No OpenAI voice response is required.
            "output_modalities": [
                "text"
            ],

            "audio": {

                "input": {

                    # main.py converts the G2 microphone
                    # from 16 kHz PCM to 24 kHz PCM.
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },

                    # G2 glasses behave more like a
                    # far-field microphone than a headset mic.
                    "noise_reduction": {
                        "type": "far_field",
                    },

                    # ------------------------------------------------
                    # TRANSCRIPTION
                    # ------------------------------------------------

                    "transcription": {

                        "model":
                            "gpt-4o-mini-transcribe",

                        # Explicit language improves transcription
                        # accuracy and latency.
                        "language": "en",

                        # IMPORTANT:
                        # Do NOT include a prompt here.
                        #
                        # Your previous prompt occasionally appeared
                        # as an actual transcript:
                        #
                        # "A professional job interview..."
                        #
                        # Removing it prevents that leakage.
                    },

                    # ------------------------------------------------
                    # VOICE ACTIVITY DETECTION
                    # ------------------------------------------------

                    "turn_detection": {

                        "type":
                            "server_vad",

                        # Slightly easier speech activation than 0.58.
                        "threshold":
                            0.50,

                        # Preserve the beginning of speech.
                        "prefix_padding_ms":
                            250,

                        # Previous value = 650 ms.
                        #
                        # Reduce to 400 ms so the completed
                        # transcription arrives sooner after
                        # interviewer stops speaking.
                        "silence_duration_ms":
                            400,

                        # We only want transcription.
                        # Our Responses API call generates
                        # the actual interview answer.
                        "create_response":
                            False,

                        # Do not let the realtime model
                        # interrupt anything automatically.
                        "interrupt_response":
                            False,
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

    return ws# ============================================================

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
