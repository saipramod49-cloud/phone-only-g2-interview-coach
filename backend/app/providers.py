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
technical knowledge. Do not require candidate evidence for general
concepts such as GCP, BigQuery, Snowflake, Dataflow, Dataproc, dbt,
SQL, ETL, data modeling, networking, or cloud architecture.

Answer naturally in first person when appropriate.

Give the direct answer immediately.

Keep the answer concise enough for smart glasses:
usually 3 to 5 short lines.

For comparison questions:
- state the main difference first
- give the important technical distinction
- give a practical use case if useful

For experience questions:
- use only the supplied candidate evidence
- never invent experience, employers, projects, dates, metrics,
  responsibilities, or outcomes

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
