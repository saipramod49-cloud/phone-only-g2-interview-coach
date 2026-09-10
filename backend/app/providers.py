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

Answer like an experienced Data Engineer speaking in an interview.

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

This is extremely important.

Default answer:
- 45 to 65 words
- usually 3 short sentences
- absolute maximum: 75 words

Do not exceed 75 words.

Even if the question is broad, give only the most important points.

The interviewer can ask follow-up questions.

Do not try to explain every possible detail.

For a complex architecture or scenario question:
1. give the main approach
2. mention the most important technologies or checks
3. finish with the validation, result, or recovery step

CANDIDATE EVIDENCE

CANDIDATE EVIDENCE may contain information from:
- resume
- professional profile
- roles and responsibilities
- project notes
- job description
- interview preparation documents

When the question asks about:
- my experience
- my current project
- my previous projects
- responsibilities
- technologies I used
- challenges I faced
- production issues
- implementation examples
- achievements

use CANDIDATE EVIDENCE as the primary source.

Never invent:
- employer names
- client names
- projects
- dates
- metrics
- responsibilities
- technologies
- achievements
- outcomes

If there is enough evidence, answer confidently as the candidate.

If evidence is incomplete, use only what is supported.

Do not say:
"I don't have enough context"
unless there is truly no relevant candidate evidence available.

GENERAL TECHNICAL QUESTIONS

For general technical questions, answer using accurate technical
knowledge even when candidate evidence is unavailable.

Do not refuse a normal technical question because the evidence
does not mention the technology.

If relevant candidate evidence exists, connect it briefly to practical
experience.

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

Do not capitalize phrases merely for emphasis.

Do not use Markdown bold.
Do not use asterisks.
Do not use headings.
Do not use tables.

COMPARISON QUESTIONS

For questions comparing two technologies:
- state the main difference
- explain one practical distinction
- say when each is appropriate

Keep the answer conversational.

SCENARIO QUESTIONS

For questions like:
"How would you..."
"Suppose..."
"What if..."
"How do you troubleshoot..."

Use a simple sequence:

"I'd first..."
"Then..."
"Finally..."

Mention only the most important actions.

EXPERIENCE QUESTIONS

For questions such as:
"Tell me about your project"
"Tell me about a challenge"
"Give me an example"
"What are your responsibilities?"

Use this compact structure:

context -> what I did -> result

Use only supported candidate evidence.

Do not repeat the interview question.

Do not provide coaching commentary.

Return only the answer the candidate should say.
""".strip()


MAX_WORDS = 72


def _clean_output(text: str) -> str:
    """
    Normalize model output for the Even glasses renderer.
    """

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
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n+",
        " ",
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
    """
    Hard-stop overly long responses so Even never receives a
    large answer that is difficult to render.
    """

    text = _clean_output(text)

    words = text.split()

    if len(words) <= max_words:
        return text

    shortened = " ".join(
        words[:max_words]
    )

    # Prefer ending at the last complete sentence if it is not
    # dramatically shorter.
    last_period = max(
        shortened.rfind("."),
        shortened.rfind("?"),
        shortened.rfind("!"),
    )

    if last_period >= int(
        len(shortened) * 0.65
    ):
        shortened = shortened[
            : last_period + 1
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
    target_size: int = 220,
):
    """
    Send a very small number of larger chunks to Even.

    This minimizes repeated renderer updates.
    """

    text = _limit_words(
        text
    )

    if not text:
        return

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    current = ""

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        candidate = (
            f"{current} {sentence}".strip()
            if current
            else sentence
        )

        if (
            current
            and len(candidate)
            > target_size
        ):
            yield current + " "
            current = sentence
        else:
            current = candidate

    if current:
        yield current


async def answer_stream(
    question: str,
    evidence: str,
):
    key = os.environ[
        "OPENAI_API_KEY"
    ]

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
                    "INTERVIEW QUESTION:\n"
                    f"{question}\n\n"
                    "CANDIDATE EVIDENCE:\n"
                    f"{evidence}\n\n"
                    "Answer exactly as the candidate "
                    "should say it aloud.\n\n"
                    "Important: keep the complete answer "
                    "under 75 words."
                ),
            },
        ],
        "max_output_tokens": 110,
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
                "Authorization":
                    f"Bearer {key}",
                "Content-Type":
                    "application/json",
            },
            json=payload,
        ) as response:

            if (
                response.status_code
                >= 400
            ):
                body = await (
                    response.aread()
                )

                body_text = body.decode(
                    "utf-8",
                    errors="replace",
                )

                print(
                    "OPENAI RESPONSES API "
                    "ERROR STATUS:",
                    response.status_code,
                    flush=True,
                )

                print(
                    "OPENAI RESPONSES API "
                    "ERROR BODY:",
                    body_text,
                    flush=True,
                )

                raise RuntimeError(
                    "OpenAI Responses API "
                    "failed: "
                    f"{response.status_code} "
                    f"{body_text}"
                )

            full = ""

            async for line in (
                response.aiter_lines()
            ):

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
                except (
                    json.JSONDecodeError
                ):
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

            for chunk in (
                _display_chunks(
                    full
                )
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
