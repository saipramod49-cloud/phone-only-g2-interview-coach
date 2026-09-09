from __future__ import annotations

import json
import os

import httpx
import websockets


SYSTEM = """
You are answering a technical job interview question as the candidate.

Use only facts supported by CANDIDATE EVIDENCE when the interviewer
asks about my actual experience, employers, projects, responsibilities,
dates, metrics, tools I used, or outcomes.

For general technical questions, answer using accurate technical
knowledge. Candidate evidence is not required for general questions
about topics such as GCP, Snowflake, BigQuery, Dataflow, Dataproc,
PySpark, Kafka, SQL, ETL, dbt, data modeling, cloud architecture,
networking, databases, or data engineering.

Answer naturally in first person when appropriate.

Give the direct answer immediately.

Keep the response concise for smart glasses:
usually 3 to 5 short lines.

For comparison questions:
- state the main difference first
- explain the important technical distinction
- give a practical use case when useful

For experience questions:
- use only the supplied candidate evidence
- never invent employers
- never invent projects
- never invent dates
- never invent metrics
- never invent responsibilities
- never invent outcomes

Do not start with:
"Sure"
"Certainly"
"Of course"
"Based on the provided evidence"

Do not provide coaching or commentary.
Only answer the interview question.
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
        json.dumps(session_update)
    )

    return ws
