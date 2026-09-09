from __future__ import annotations

import json
import os

import httpx
import websockets


SYSTEM = """
You are answering a technical job interview question as the candidate.

Use only facts supported by CANDIDATE EVIDENCE when the question asks
about my experience, employers, projects, responsibilities, dates,
metrics, tools I used, or outcomes.

For general technical questions, answer directly using accurate
technical knowledge.

Answer directly and naturally.

Keep the answer concise enough for smart glasses:
usually 3 to 5 short lines.

For comparison questions:
- state the main difference first
- give the key technical distinction
- give a practical example if useful

For experience questions:
- use only the supplied candidate evidence
- never invent experience, employers, projects, dates, metrics,
  responsibilities, or outcomes

Do not start with:
"Sure"
"Certainly"
"Of course"
"Based on the provided evidence"

Do not coach.
Just answer the interviewer.
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

            if response.status_code >= 400:
                body = await response.aread()

                body_text = body.decode(
                    "utf-8",
                    errors="replace",
                )

                print(
                    "OPENAI RESPONSES API ERROR STATUS:",
                    response.status_code,
                    flush=True,
                )

                print(
                    "OPENAI RESPONSES API ERROR BODY:",
                    body_text,
                    flush=True,
                )

                raise RuntimeError(
                    f"OpenAI Responses API failed: "
                    f"{response.status_code} "
                    f"{body_text}"
                )

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

                if (
                    event.get("type")
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
        ping_interval=10,
        ping_timeout=10,
        close_timeout=5,
    )

    session_update = {
        "type": "session.update",

        "session": {

            "type": "realtime",

            "output_modalities": [
                "text"
            ],

            "audio": {

                "input": {

                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },

                    "noise_reduction": {
                        "type": "far_field",
                    },

                    "transcription": {
                        "model": "gpt-4o-mini-transcribe",
                        "language": "en",
                    },

                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.50,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 450,
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

    return ws"Certainly"
"Of course"
"Based on the provided evidence"

Do not coach.
Just answer the interviewer.
""".strip()


# ============================================================
# ANSWER GENERATION
# ============================================================

async def answer_stream(
    question: str,
    evidence: str,
):
    key = os.environ["OPENAI_API_KEY"]

    # Use a current Responses API model.
    model = os.getenv(
        "OPENAI_MODEL",
        "gpt-5.6-luna",
    )

    payload = {
        "model": model,

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

            if response.status_code >= 400:

                body = await response.aread()

                body_text = body.decode(
                    "utf-8",
                    errors="replace",
                )

                print(
                    "OPENAI RESPONSES API ERROR STATUS:",
                    response.status_code,
                    flush=True,
                )

                print(
                    "OPENAI RESPONSES API ERROR BODY:",
                    body_text,
                    flush=True,
                )

                raise RuntimeError(
                    f"OpenAI Responses API failed: "
                    f"{response.status_code} "
                    f"{body_text}"
                )

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
        ping_interval=10,
        ping_timeout=10,
        close_timeout=5,
    )

    session_update = {
        "type": "session.update",

        "session": {

            "type": "realtime",

            "output_modalities": [
                "text"
            ],

            "audio": {

                "input": {

                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },

                    "noise_reduction": {
                        "type": "far_field",
                    },

                    "transcription": {
                        "model":
                            "gpt-4o-mini-transcribe",

                        "language":
                            "en",
                    },

                    "turn_detection": {

                        "type":
                            "server_vad",

                        "threshold":
                            0.50,

                        "prefix_padding_ms":
                            300,

                        "silence_duration_ms":
                            450,

                        "create_response":
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

    return ws  responsibilities, or outcomes

Do not start with:
"Sure"
"Certainly"
"Of course"
"Based on the provided evidence"

Do not provide interview coaching.
Just answer the interviewer.
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
        "gpt-5-mini",
    )

    payload = {
        "model": model,
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

            if response.status_code >= 400:
                error_body = await response.aread()

                print(
                    "OPENAI RESPONSES API ERROR:",
                    response.status_code,
                    error_body.decode(
                        "utf-8",
                        errors="replace",
                    ),
                    flush=True,
                )

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
        ping_interval=10,
        ping_timeout=10,
        close_timeout=5,
    )

    session_update = {
        "type": "session.update",

        "session": {

            "type": "realtime",

            # We only need text/transcription.
            # The glasses application handles display.
            "output_modalities": [
                "text"
            ],

            "audio": {

                "input": {

                    # Even G2 microphone:
                    # PCM16 / 16 kHz / mono.
                    #
                    # main.py converts the audio to
                    # 24 kHz before sending it here.
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },

                    # G2 microphone behaves like a
                    # far-field microphone.
                    "noise_reduction": {
                        "type": "far_field",
                    },

                    # =================================================
                    # TRANSCRIPTION
                    # =================================================

                    "transcription": {

                        "model":
                            "gpt-4o-mini-transcribe",

                        "language":
                            "en",

                        # IMPORTANT:
                        #
                        # Do NOT add a transcription prompt here.
                        #
                        # The previous prompt:
                        #
                        # "A professional job interview..."
                        #
                        # was occasionally returned as if the
                        # interviewer had actually spoken it.
                    },

                    # =================================================
                    # VOICE ACTIVITY DETECTION
                    # =================================================

                    "turn_detection": {

                        "type":
                            "server_vad",

                        # Detect normal interview speech.
                        "threshold":
                            0.50,

                        # Preserve beginning of sentences.
                        "prefix_padding_ms":
                            300,

                        # Previously 650 ms.
                        #
                        # 450 ms provides faster question
                        # completion while allowing short
                        # natural pauses.
                        "silence_duration_ms":
                            450,

                        # We only want transcription from
                        # this realtime connection.
                        #
                        # Answers are generated separately
                        # through answer_stream().
                        "create_response":
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

    return ws  responsibilities, or outcomes

Do not start with:
"Sure"
"Certainly"
"Of course"
"Based on the provided evidence"

Do not provide interview coaching.
Just answer the interviewer.
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
        "gpt-5-mini",
    )

    payload = {
        "model": model,
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

        "max_output_tokens": 180,
    }

    # Only add reasoning configuration for models
    # where the account/model supports it.
    if model.startswith("gpt-5"):
        payload["reasoning"] = {
            "effort": "minimal"
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

                if (
                    event.get("type")
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
        ping_interval=10,
        ping_timeout=10,
        close_timeout=5,
    )

    session_update = {
        "type": "session.update",

        "session": {
            "type": "realtime",

            "output_modalities": [
                "text"
            ],

            "audio": {
                "input": {

                    # main.py receives Even G2 PCM16 at 16 kHz
                    # and resamples it to 24 kHz before sending.
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    },

                    "noise_reduction": {
                        "type": "far_field",
                    },

                    # IMPORTANT:
                    # There is deliberately NO transcription
                    # prompt here. The previous prompt was
                    # occasionally hallucinated as spoken text.
                    "transcription": {
                        "model":
                            "gpt-4o-mini-transcribe",

                        "language":
                            "en",
                    },

                    "turn_detection": {
                        "type":
                            "server_vad",

                        "threshold":
                            0.50,

                        "prefix_padding_ms":
                            300,

                        # Faster than the previous 650 ms,
                        # while still allowing short pauses.
                        "silence_duration_ms":
                            450,

                        "create_response":
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

    return ws
