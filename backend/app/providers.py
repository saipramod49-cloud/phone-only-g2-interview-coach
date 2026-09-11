from __future__ import annotations

import asyncio
import json
import os
import re

import httpx
import websockets


SYSTEM = """
You are answering a technical job interview as the candidate.

The answer is displayed on smart glasses.

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

Give only the most important points.
The interviewer can ask follow-up questions.

CONVERSATION CONTEXT

The interview may be a continuous conversation.

A later question may refer to something discussed earlier using phrases like:
"why?"
"how?"
"what happened next?"
"what did you do?"
"why did you choose that?"
"what if that fails?"
"how did you solve it?"

Use prior conversation only to understand what the interviewer is referring to
and to maintain continuity.

Do not treat prior conversational statements as verified professional evidence.

If the candidate previously gave an answer, stay consistent with the same
technical concept unless the interviewer explicitly changes the topic.

Always prioritize answering the newest interviewer question.

CANDIDATE EVIDENCE

Candidate evidence contains verified information retrieved from uploaded
resume, project notes, roles and responsibilities, and related material.

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

use CANDIDATE EVIDENCE as the factual source.

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

Every concrete personal-experience claim must be supported by candidate
evidence.

If evidence does not support a specific incident, do not invent one.

GENERAL TECHNICAL QUESTIONS

For purely technical or hypothetical questions, use accurate general
technical knowledge.

Candidate evidence is not required for conceptual questions.

If relevant verified experience exists, connect it briefly.

KEYWORD HIGHLIGHTING

The glasses do not reliably render Markdown formatting.

Do not use:
**bold**
_italics_
Markdown headings
tables

Highlight only 2 to 4 of the most important technical terms by writing
those terms in UPPERCASE.

Good examples:
BIGQUERY
DATAFLOW
PUB/SUB
CDC
MERGE
IAM
SNOWFLAKE
PYSPARK
SCD TYPE II

Do not uppercase ordinary sentences.
Do not uppercase more than 4 technical terms.
Keep the answer visually natural.

Example:

"I'd land the CDC records in BIGQUERY, deduplicate by business key and
event timestamp, then use MERGE to maintain SCD TYPE II history. For
late events, I'd process using the source event time rather than the
arrival time and validate the resulting effective-date ranges."

COMPARISON QUESTIONS

State:
1. the main difference
2. the most important practical distinction
3. when each is appropriate

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

Only use supported candidate evidence.

FOLLOW-UP QUESTIONS

If the latest question is short or ambiguous, infer its meaning from the
immediately preceding interview discussion.

Examples:

Previous topic:
BigQuery partitioning

Question:
"Why did you choose that?"

Answer about the previously discussed partitioning decision.

Previous topic:
production reconciliation issue

Question:
"How did you identify it?"

Continue that same supported example rather than starting a different story.

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


def _display_chunks(text: str):
    text = _limit_words(text)

    if text:
        yield text


async def answer_stream(
    question: str,
    evidence: str,
    conversation_context: str = "",
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
                    "LATEST INTERVIEW QUESTION:\n"
                    f"{question}\n\n"
                    "RECENT CONVERSATION CONTEXT:\n"
                    f"{conversation_context or 'No earlier conversation supplied.'}\n\n"
                    "VERIFIED CANDIDATE EVIDENCE:\n"
                    f"{evidence}\n\n"
                    "Answer exactly as the candidate should say it aloud.\n"
                    "Answer the newest question first.\n"
                    "Stay consistent with the recent conversation.\n"
                    "Do not treat conversation context as verified work experience.\n"
                    "Keep the complete answer under 65 words.\n"
                    "Highlight only 2 to 4 important technical keywords using uppercase."
                ),
            },
        ],
        "max_output_tokens": 1600,
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
            completed = False

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
                        yield delta

                if event.get("type") == "response.completed":
                    completed = True
                if event.get("type") in ("error", "response.failed", "response.incomplete"):
                    raise RuntimeError("OpenAI answer stream did not complete")

            if not full or not completed:
                raise RuntimeError("OpenAI answer stream ended without a complete answer")


def transcription_diagnostic(error):
    # Never log exception text, headers, URLs, audio, tokens or API response bodies.
    fields = {"exception": type(error).__name__}
    status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int):
        fields["http_status"] = status
    if isinstance(error, KeyError) and error.args == ("OPENAI_API_KEY",):
        fields["reason"] = "OPENAI_API_KEY_missing"
    if isinstance(error, TimeoutError):
        fields["reason"] = "OpenAI_setup_timeout"
    fields.update(getattr(error, "safe_details", {}))
    return json.dumps(fields)


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

    try:
        async with asyncio.timeout(15):
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") == "session.updated":
                    return ws
                if event.get("type") == "error":
                    failure = RuntimeError("OpenAI rejected transcription configuration")
                    details = event.get("error") or {}
                    # Only machine-readable codes and parameter names, never raw messages.
                    failure.safe_details = {
                        name: str(details[name])[:100]
                        for name in ("type", "code", "param")
                        if details.get(name) is not None
                        and re.fullmatch(r"[A-Za-z0-9_.\[\]-]{1,100}", str(details[name]))
                    }
                    raise failure
            raise RuntimeError("OpenAI transcription connection closed")
    except BaseException:
        await ws.close()
        raise

