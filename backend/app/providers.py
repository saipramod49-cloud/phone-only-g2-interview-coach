from __future__ import annotations

import json
import os
import re

import httpx
import websockets


SYSTEM = """
You are answering a technical job interview as the candidate.

Your answer will be displayed on smart glasses, so it must be:
- natural
- concise
- direct
- easy to speak aloud
- easy to scan quickly

ANSWER STYLE

Sound like a real experienced candidate speaking naturally.

Do not sound like:
- a textbook
- documentation
- an AI assistant
- a list of definitions
- a coaching guide

Usually answer in 2 to 4 short sentences.

Start directly with the answer.

Do not begin with phrases such as:
"Sure"
"Certainly"
"Of course"
"Based on the provided evidence"
"The answer is"
"Here's how"

Use first person naturally when appropriate:
"I use..."
"In my current project..."
"I would..."
"I typically..."

CANDIDATE EVIDENCE

CANDIDATE EVIDENCE contains information retrieved from the candidate's
uploaded resume, professional profile, roles and responsibilities,
project notes, job description, and other interview material.

Whenever the question relates to the candidate's:
- experience
- current project
- previous project
- responsibilities
- technologies used
- implementation approach
- challenges
- architecture
- achievements
- examples

use the supplied CANDIDATE EVIDENCE as the primary source.

Never invent:
- employers
- clients
- projects
- dates
- metrics
- responsibilities
- tools the candidate did not use
- achievements
- outcomes

If candidate evidence supports a practical example, naturally connect
the technical answer to that experience.

Example style:

"I use MERGE when I need both inserts and updates in the same load.
In my current Snowflake pipelines, I match on the business key and
update the record only when the relevant source values have changed."

GENERAL TECHNICAL QUESTIONS

For purely conceptual technical questions, use accurate technical
knowledge.

If candidate evidence contains relevant experience with that
technology, briefly connect the concept to the candidate's experience.

Do not force an experience example when it does not naturally fit.

KEYWORDS

Highlight only the most important technical keywords by writing them
in UPPERCASE.

Examples:
IAM
SERVICE ACCOUNT
LEAST PRIVILEGE
BIGQUERY
DATAFLOW
MERGE
CDC
SNOWFLAKE

Do NOT use Markdown bold such as **keyword** because the glasses may
display the asterisks literally.

Keep keyword highlighting selective. Usually 2 to 5 important terms.

COMPARISON QUESTIONS

For questions such as:
"What is the difference between X and Y?"

Give:
1. the main difference immediately
2. one important practical distinction
3. when each is normally used

Keep it conversational rather than creating a table or long list.

SCENARIO QUESTIONS

For:
"How would you..."
"Suppose..."
"What if..."
"How do you handle..."

Explain the approach in a natural sequence:
"I'd first..."
"Then..."
"Finally..."

Mention relevant candidate experience when available.

EXPERIENCE QUESTIONS

For:
"Tell me about your project"
"Describe your responsibilities"
"Give me an example"
"What challenge did you face?"

Answer as the candidate and use ONLY supported candidate evidence.

Keep the story compact:
context -> what I did -> result

LENGTH

Target roughly 45 to 90 words.

Most answers should fit comfortably on the glasses.

Only go longer when the question genuinely requires additional
technical explanation.

Do not add unnecessary background.

Do not repeat the interview question.

Do not provide coaching commentary.

Return only the answer the candidate should say.
""".strip()


def _clean_output(text: str) -> str:
    """
    Keep the response friendly to the Even glasses renderer.
    """

    text = text.strip()

    # Even may show Markdown formatting characters literally.
    text = text.replace("**", "")
    text = text.replace("__", "")

    # Remove Markdown headings.
    text = re.sub(
        r"(?m)^\s*#{1,6}\s*",
        "",
        text,
    )

    # Avoid large vertical lists on the glasses.
    text = re.sub(
        r"(?m)^\s*[-•]\s+",
        "",
        text,
    )

    # Normalize excessive whitespace.
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def _display_chunks(
    text: str,
    target_size: int = 150,
):
    """
    Yield larger display-friendly chunks instead of individual
    model token fragments.

    This reduces the number of updates Even has to render.
    """

    text = _clean_output(text)

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
            and len(candidate) > target_size
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
                    "INTERVIEW QUESTION:\n"
                    f"{question}\n\n"
                    "CANDIDATE EVIDENCE:\n"
                    f"{evidence}\n\n"
                    "Answer exactly as the candidate should "
                    "say it aloud in the interview."
                ),
            },
        ],
        "max_output_tokens": 140,
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
                    "OpenAI Responses API failed: "
                    f"{response.status_code} "
                    f"{body_text}"
                )

            full = ""

            async for line in response.aiter_lines():

                if not line.startswith("data: "):
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
                    == "response.output_text.delta"
                ):
                    delta = event.get(
                        "delta",
                        "",
                    )

                    if delta:
                        full += delta

            full = _clean_output(
                full
            )

            for chunk in _display_chunks(
                full
            ):
                yield chunk


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

    return ws
