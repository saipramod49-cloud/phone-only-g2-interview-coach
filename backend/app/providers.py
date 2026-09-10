from __future__ import annotations

import json
import os
import re

import httpx
import websockets


SYSTEM = """
You are answering a technical job interview as the candidate.

The answer will be displayed on smart glasses.

Your response must be:
- concise
- natural
- technically accurate
- easy to scan
- easy to speak aloud

STYLE

Answer like an experienced Data Engineer speaking naturally.

Do not sound like:
- documentation
- a textbook
- an AI assistant
- a coaching guide
- a long technical article

Start directly with the answer.

Do not begin with:
"Sure"
"Certainly"
"Of course"
"Based on the provided evidence"
"The answer is"
"Here's how"

Use first person naturally:
"I use..."
"I'd first..."
"In my project..."
"I typically..."

LENGTH

Default answer:
- 40 to 60 words
- usually 2 or 3 short sentences
- absolute maximum: 65 words

Never exceed 65 words.

For broad questions, give only the most important points.
The interviewer can ask follow-up questions.

CANDIDATE EVIDENCE

When the question asks about:
- my experience
- my current project
- previous projects
- responsibilities
- technologies I used
- production issues
- challenges
- implementation examples
- achievements

use CANDIDATE EVIDENCE as the primary source.

Never invent:
- employers
- clients
- projects
- incidents
- dates
- metrics
- responsibilities
- technologies
- achievements
- outcomes

For experience questions, every concrete claim must be supported by
CANDIDATE EVIDENCE.

If the evidence does not support a specific incident, do not create
a hypothetical incident and present it as something I experienced.

Instead, give the closest supported real example.

GENERAL TECHNICAL QUESTIONS

For purely technical questions, use accurate general technical knowledge.

Candidate evidence is not required for conceptual questions.

If relevant experience exists in the evidence, connect it briefly.

TECHNOLOGY NAMES

Use normal capitalization.

Examples:
BigQuery
Dataflow
Pub/Sub
Cloud Composer
GCS
Snowflake
CDC
IAM
SCD Type II
SQL
PySpark

Do not use uppercase words just for emphasis.

Do not use Markdown.
Do not use headings.
Do not use bullets.
Do not use tables.

COMPARISON QUESTIONS

State:
- the main difference
- the most important practical distinction
- when each is appropriate

Keep it conversational.

SCENARIO QUESTIONS

Use a short natural sequence:
"I'd first..."
"Then..."
"Finally..."

Mention only the most important actions.

EXPERIENCE QUESTIONS

Use:
context -> what I did -> result

Only use supported evidence.

Do not repeat the interview question.
Do not provide coaching commentary.

Return only the answer the candidate should say.
""".strip()


MAX_WORDS = 65


def _clean_output(text: str) -> str:
    text = text.strip()

    text = text.replace("**", "")
    text = text.replace("__", "")

    text = re.sub(
        r"(?m)^\s*#{1,6}\s*",
        "",
        text,
    )

    text = re.sub(
        r"(?m)^\s*[-•]\s+",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _limit_words(
    text: str,
    max_words: int = MAX_WORDS,
) -> str:
    text = _clean_output(text)

    words = text.split()

    if len(words) <= max_words:
        return text

    shortened = " ".join(
        words[:max_words]
    )

    last_end = max(
        shortened.rfind("."),
        shortened.rfind("?"),
        shortened.rfind("!"),
    )

    if last_end >= int(
        len(shortened) * 0.60
    ):
        shortened = shortened[
            :last_end + 1
        ]
    else:
        shortened = (
            shortened.rstrip(
                ",;:-"
            )
            + "."
        )

    return shortened.strip()


def _display_chunks(
    text: str,
):
    """
    Return the complete short answer as one display chunk.

    Even has shown instability when receiving multiple content
    updates, so minimize renderer updates.
    """

    text = _limit_words(text)

    if text:
        yield text


async def answer_stream(
    question: str,
    evidence: str,
):
    key = os.environ[
        "OPENAI_API_KEY"
    ]

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
                    "INTERVIEW QUESTION:\n"
                    f"{question}\n\n"
                    "CANDIDATE EVIDENCE:\n"
                    f"{evidence}\n\n"
                    "Answer exactly as the candidate "
                    "should say it aloud.\n"
                    "Keep the complete answer under "
                    "65 words."
                ),
            },
        ],
        "max_output_tokens": 220,
    }

    timeout = httpx.Timeout(
        connect=10.0,
        read=30.0,
        write=10.0,
        pool=10.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
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
                    "OpenAI Responses API failed: "
                    f"{response.status_code} "
                    f"{body_text}"
                )

            full = ""

            async for line in response.aiter_lines():

                if not line.startswith(
                    "data: "
                ):
                    continue

                data = line[6:]

                if data == "[DONE]":
                    break

                try:
                    event = json.loads(
                        data
                    )
                except json.JSONDecodeError:
                    continue

                if (
                    event.get("type")
                    ==
                    "response.output_text.delta"
                ):
                    delta = event.get(
                        "delta",
                        "",
                    )

                    if delta:
                        full += delta

            full = _limit_words(
                full
            )

            if not full:
                raise RuntimeError(
                    "OpenAI returned an empty answer"
                )

            for chunk in _display_chunks(
                full
            ):
                yield chunk


async def openai_transcription_session():
    key = os.environ[
        "OPENAI_API_KEY"
    ]

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

    return ws
