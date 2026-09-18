"""
GPT-Live experimental backend for Interview Lens.

This module preserves the existing phone/G2 websocket protocol so
the Even Hub frontend does not need to be rebuilt.

Flow:

G2 microphone
    -> Render /ws/live
    -> GPT-Live-1
    -> semantic conversation understanding
    -> Responses delegation
    -> backend reasoning model
    -> answer.delta
    -> G2 display

Enable by setting:

OPENAI_LIVE_EXPERIMENT=1

Set OPENAI_LIVE_EXPERIMENT=0 to restore backend/app/live.py.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import time
import uuid

from contextlib import suppress

import websockets

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)

from .models import (
    account_models,
    AnswerModelError,
)


router = APIRouter()


# ============================================================
# CONFIGURATION
# ============================================================

LIVE_MODEL = os.getenv(
    "OPENAI_LIVE_MODEL",
    "gpt-live-1",
)

BACKEND_MODEL = os.getenv(
    "OPENAI_LIVE_BACKEND_MODEL",
    "gpt-5.6-terra",
)


# ============================================================
# GPT-LIVE LISTENING PROMPT
# ============================================================

LIVE_INSTRUCTIONS = """
You are the listening layer for a technical interview assistant.

Your most important job is determining WHEN the interviewer has
finished asking the complete question.

The interviewer may:

- speak slowly
- pause for several seconds
- tell a long story before asking the question
- give multiple constraints
- correct something said earlier
- ask several related subquestions
- describe a production incident before asking what should be done
- use technical terminology
- speak conversationally rather than using perfect grammar

DO NOT treat a normal pause as the end of the question.

DO NOT delegate while the interviewer is still giving:

- setup
- scenario
- constraints
- examples
- corrections
- background

Wait until the complete actionable request is clear.

For every completed technical interview question, delegate the task
to the configured Responses backend.

Do not answer substantive technical interview questions yourself.

The backend agent provides the actual answer.

The application displays that answer as text on smart glasses.

Do not read the full answer aloud.

After delegation, wait until the application explicitly resumes
microphone capture before treating new speech as another question.

If the speaker is merely thinking aloud, providing background, or
has not reached an actionable request yet, continue listening.

Prefer waiting slightly longer over prematurely answering an
incomplete question.
""".strip()


# ============================================================
# BACKEND ANSWER PROMPT
# ============================================================

BACKEND_INSTRUCTIONS = """
You are the reasoning backend for a live technical interview assistant.

The user is interviewing for senior Data Engineering roles.

The answer will appear on smart glasses and the candidate will speak
it naturally.

ANSWER STYLE

Answer exactly as an experienced Data Engineer would answer aloud.

Do not sound like:

- documentation
- a textbook
- an AI assistant
- a tutorial
- a coaching guide

Start directly with the answer.

Do not begin with:

"Sure"
"Certainly"
"Of course"
"Here's how"
"The answer is"

Use natural first-person language when appropriate:

"I'd first..."
"I would check..."
"I normally..."
"In that situation..."

COMPLETENESS

Carefully identify every part of the interviewer question.

For multipart questions, answer every requested part.

For scenario questions:

1. identify what is probably happening
2. explain how you would investigate it
3. explain how you would fix it
4. mention an important tradeoff or prevention step when relevant

Do not ignore the final clause of a long question.

TECHNICAL DEPTH

Answer at senior Data Engineer level.

Use accurate production concepts where relevant, including:

- BigQuery
- GCS
- Airflow
- Spark
- PySpark
- Dataproc
- Dataflow
- Kafka
- Pub/Sub
- Snowflake
- Databricks
- SQL
- Python
- partitioning
- clustering
- data skew
- shuffle
- executor memory
- CDC
- idempotency
- schema evolution
- observability
- data quality
- retries
- replay
- transactional processing

Do not force technologies into an answer when they are not relevant.

LENGTH

For a straightforward question:
roughly 70 to 130 words.

For a complex scenario or multipart question:
roughly 120 to 250 words.

Do not make the answer artificially short when the interviewer asks
a complex scenario.

SMART-GLASSES FORMAT

Use short paragraphs.

Avoid Markdown tables.

Avoid long headings.

Avoid unnecessary bullet lists.

Return only the answer that the candidate should say aloud.

PERSONAL EXPERIENCE

This experimental GPT-Live mode currently focuses on conversational
understanding and question completion.

Do not invent personal employment incidents, metrics, achievements,
clients, dates, or project facts.

If a question explicitly requires personal experience and no verified
candidate evidence is available in the Live context, give a clearly
general or hypothetical engineering approach rather than fabricating
experience.
""".strip()


# ============================================================
# MODEL LIST ENDPOINT
# ============================================================

@router.get("/api/models")
async def list_answer_models(
    x_app_token: str | None = Header(None),
):
    expected = os.getenv(
        "APP_TOKEN",
        "",
    )

    if (
        not expected
        or not isinstance(
            x_app_token,
            str,
        )
        or not hmac.compare_digest(
            expected,
            x_app_token,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid app access token",
        )

    try:
        return {
            "models":
                await account_models(),

            "note":
                "GPT-Live experiment uses OPENAI_LIVE_BACKEND_MODEL.",
        }

    except AnswerModelError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from None


# ============================================================
# SAFE PROVIDER ERROR DETAILS
# ============================================================

def safe_error_details(
    event: dict,
) -> dict:

    error = event.get(
        "error",
    )

    if not isinstance(
        error,
        dict,
    ):
        return {}

    allowed = {}

    for field in (
        "type",
        "code",
        "param",
    ):
        value = error.get(
            field,
        )

        if value is not None:
            allowed[field] = str(
                value
            )[:120]

    return allowed


# ============================================================
# OPEN GPT-LIVE SESSION
# ============================================================

async def open_gpt_live_session():

    key = os.getenv(
        "OPENAI_API_KEY"
    )

    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing on Render"
        )

    connection = await websockets.connect(
        "wss://api.openai.com/v1/live/sessions",

        additional_headers={
            "Authorization":
                f"Bearer {key}",
        },

        ping_interval=10,
        ping_timeout=10,
        close_timeout=5,

        max_size=4 * 1024 * 1024,
    )

    start_event = {
        "type":
            "session.start",

        "event_id":
            "g2_start_"
            + uuid.uuid4().hex,

        "session": {
            "model":
                LIVE_MODEL,

            "instructions":
                LIVE_INSTRUCTIONS,

            # Even G2 microphone stream is PCM16 mono at 16 kHz.
            "audio": {
                "format": {
                    "type":
                        "audio/pcm",

                    "rate":
                        16000,
                },

                # We ignore returned speech audio because answers
                # are shown as text on the G2 display.
                "output": {
                    "voice":
                        "marin",
                },
            },

            "delegation": {
                "type":
                    "responses",

                "responses": {
                    "model":
                        BACKEND_MODEL,

                    "instructions":
                        BACKEND_INSTRUCTIONS,

                    "max_output_tokens":
                        900,
                },
            },

            "store":
                False,
        },
    }

    await connection.send(
        json.dumps(
            start_event
        )
    )

    try:

        async with asyncio.timeout(
            20
        ):

            async for raw in connection:

                event = json.loads(
                    raw
                )

                kind = event.get(
                    "type",
                    "",
                )

                if kind == "session.started":

                    session = event.get(
                        "session",
                        {},
                    )

                    print(
                        "GPT_LIVE_STARTED",
                        session.get(
                            "id",
                            "",
                        ),
                        flush=True,
                    )

                    return connection

                if kind == "error":

                    details = (
                        safe_error_details(
                            event
                        )
                    )

                    print(
                        "GPT_LIVE_START_ERROR",
                        json.dumps(
                            details
                        ),
                        flush=True,
                    )

                    raise RuntimeError(
                        "OpenAI rejected the GPT-Live session configuration"
                    )

        raise RuntimeError(
            "GPT-Live session start timed out"
        )

    except BaseException:

        with suppress(
            Exception
        ):
            await connection.close()

        raise


# ============================================================
# LIVE WEBSOCKET USED BY EVEN INTERVIEW LENS
# ============================================================

@router.websocket(
    "/ws/live"
)
async def live(
    ws: WebSocket,
):

    await ws.accept()

    openai = None
    reader = None

    send_lock = asyncio.Lock()

    state = {
        "authenticated":
            False,

        "listening":
            False,

        "muted":
            False,

        "transcript":
            "",

        # Transcript fragments before this timestamp belong to
        # the question that has already been processed.
        "cut_ms":
            -1,

        "speaker":
            "unknown",

        "answer_text":
            {},

        "answer_started":
            set(),

        "first_text_ms":
            {},

        "question":
            {},

        "delegation_started":
            {},

        "coach_instructions":
            "",
    }


    # ========================================================
    # SEND EVENT TO PHONE / G2
    # ========================================================

    async def send(
        kind: str,
        **fields,
    ):

        async with send_lock:

            await ws.send_json(
                {
                    "type":
                        kind,

                    **fields,
                }
            )


    # ========================================================
    # OPEN OPENAI LIVE CONNECTION
    # ========================================================

    async def ensure_openai():

        nonlocal openai
        nonlocal reader

        if openai is not None:
            return

        await send(
            "state",
            message=
                "Connecting to GPT-Live…",
        )

        openai = (
            await
            open_gpt_live_session()
        )

        reader = asyncio.create_task(
            read_openai()
        )

        await send(
            "state",
            message=
                "GPT-Live connected",
        )


    # ========================================================
    # MUTE / UNMUTE GPT-LIVE INPUT
    # ========================================================

    async def mute_openai():

        if (
            openai is None
            or state["muted"]
        ):
            return

        await openai.send(
            json.dumps(
                {
                    "type":
                        "session.input_audio.mute",

                    "event_id":
                        "mute_"
                        + uuid.uuid4().hex,
                }
            )
        )

        state[
            "muted"
        ] = True


    async def unmute_openai():

        if (
            openai is None
            or not state["muted"]
        ):
            return

        await openai.send(
            json.dumps(
                {
                    "type":
                        "session.input_audio.unmute",

                    "event_id":
                        "unmute_"
                        + uuid.uuid4().hex,
                }
            )
        )

        state[
            "muted"
        ] = False


    # ========================================================
    # MANUAL "ANSWER CAPTURED QUESTION"
    # ========================================================

    async def force_answer():

        await ensure_openai()

        # Stop listening before asking for an answer.
        #
        # This prevents candidate speech from immediately
        # becoming a new interviewer question.
        state[
            "listening"
        ] = False

        await send(
            "capture",
            active=False,
        )

        with suppress(
            Exception
        ):
            await mute_openai()

        await openai.send(
            json.dumps(
                {
                    "type":
                        "response.create",

                    "event_id":
                        "manual_answer_"
                        + uuid.uuid4().hex,
                }
            )
        )

        await send(
            "flow",
            phase=
                "generating",
        )


    # ========================================================
    # READ GPT-LIVE EVENTS
    # ========================================================

    async def read_openai():

        nonlocal openai

        try:

            async for raw in openai:

                event = json.loads(
                    raw
                )

                kind = event.get(
                    "type",
                    "",
                )


                # =================================================
                # PROVIDER ERROR
                # =================================================

                if kind == "error":

                    details = (
                        safe_error_details(
                            event
                        )
                    )

                    print(
                        "GPT_LIVE_ERROR",
                        json.dumps(
                            details
                        ),
                        flush=True,
                    )

                    await send(
                        "error",
                        keep_capture=
                            state[
                                "listening"
                            ],

                        recoverable=True,

                        message=(
                            "GPT-Live reported an error. "
                            "Check Render logs."
                        ),
                    )

                    continue


                # =================================================
                # LIVE INPUT TRANSCRIPT
                # =================================================

                if (
                    kind
                    ==
                    "session.input_transcript.delta"
                ):

                    # Important:
                    #
                    # Once delegation happens listening becomes False.
                    # Therefore any delayed transcription events arriving
                    # while the candidate reads the answer are ignored.
                    if not state[
                        "listening"
                    ]:
                        continue

                    delta = event.get(
                        "delta",
                        "",
                    )

                    if not delta:
                        continue

                    end_ms = event.get(
                        "end_ms"
                    )

                    if (
                        isinstance(
                            end_ms,
                            (int, float),
                        )
                        and
                        end_ms
                        <=
                        state[
                            "cut_ms"
                        ]
                    ):
                        continue

                    state[
                        "transcript"
                    ] += delta

                    # Avoid unlimited transcript growth.
                    if (
                        len(
                            state[
                                "transcript"
                            ]
                        )
                        >
                        16000
                    ):
                        state[
                            "transcript"
                        ] = state[
                            "transcript"
                        ][-12000:]

                    await send(
                        "transcript.partial",

                        text=
                            state[
                                "transcript"
                            ].strip(),
                    )

                    continue


                # =================================================
                # SEMANTIC QUESTION COMPLETE
                # =================================================

                if (
                    kind
                    ==
                    "session.delegation.created"
                ):

                    delegation = event.get(
                        "delegation",
                        {},
                    )

                    if not isinstance(
                        delegation,
                        dict,
                    ):
                        continue

                    if (
                        delegation.get(
                            "target"
                        )
                        !=
                        "responses"
                    ):
                        continue

                    delegation_id = (
                        delegation.get(
                            "id"
                        )
                    )

                    if not delegation_id:
                        continue

                    question = (
                        state[
                            "transcript"
                        ]
                        .strip()
                    )

                    offset_ms = event.get(
                        "offset_ms"
                    )

                    if isinstance(
                        offset_ms,
                        (int, float),
                    ):
                        state[
                            "cut_ms"
                        ] = offset_ms


                    state[
                        "question"
                    ][
                        delegation_id
                    ] = question


                    state[
                        "delegation_started"
                    ][
                        delegation_id
                    ] = time.monotonic()


                    state[
                        "answer_text"
                    ][
                        delegation_id
                    ] = ""


                    # ============================================
                    # CRITICAL FIX
                    #
                    # Stop listening immediately once GPT-Live
                    # decides the interviewer finished the question.
                    #
                    # Otherwise the candidate begins reading the
                    # generated answer, the microphones hear that
                    # speech, and the UI replaces the answer with
                    # another QUESTION · LIVE transcript.
                    # ============================================

                    state[
                        "listening"
                    ] = False

                    state[
                        "transcript"
                    ] = ""

                    await send(
                        "capture",
                        active=False,
                    )

                    # Tell GPT-Live not to process more microphone
                    # audio during answer reading.
                    with suppress(
                        Exception
                    ):
                        await mute_openai()


                    await send(
                        "transcript.final",

                        text=(
                            question
                            or
                            "GPT-Live detected a complete question."
                        ),
                    )


                    await send(
                        "flow",
                        phase=
                            "generating",
                    )


                    await send(
                        "state",
                        message=(
                            "Question complete · microphone paused "
                            "while you read the answer"
                        ),
                    )


                    print(
                        "GPT_LIVE_DELEGATED",
                        delegation_id,
                        flush=True,
                    )

                    continue


                # =================================================
                # RESPONSES DELEGATION EVENTS
                # =================================================

                if (
                    kind
                    ==
                    "response.event"
                ):

                    delegation_id = (
                        event.get(
                            "delegation_id"
                        )
                        or
                        "manual"
                    )

                    inner = event.get(
                        "event",
                        {},
                    )

                    if not isinstance(
                        inner,
                        dict,
                    ):
                        continue

                    inner_kind = inner.get(
                        "type",
                        "",
                    )


                    # =============================================
                    # FIRST / STREAMING TEXT
                    # =============================================

                    if (
                        inner_kind
                        ==
                        "response.output_text.delta"
                    ):

                        delta = inner.get(
                            "delta",
                            "",
                        )

                        if not delta:
                            continue


                        answer_id = (
                            delegation_id
                        )


                        if (
                            delegation_id
                            not in
                            state[
                                "answer_started"
                            ]
                        ):

                            state[
                                "answer_started"
                            ].add(
                                delegation_id
                            )

                            question = (
                                state[
                                    "question"
                                ].get(
                                    delegation_id,
                                    "",
                                )
                            )

                            started = (
                                state[
                                    "delegation_started"
                                ].get(
                                    delegation_id
                                )
                            )

                            first_text_ms = None

                            if started:

                                first_text_ms = round(
                                    (
                                        time.monotonic()
                                        -
                                        started
                                    )
                                    *
                                    1000
                                )

                            state[
                                "first_text_ms"
                            ][
                                delegation_id
                            ] = (
                                first_text_ms
                            )


                            await send(
                                "answer.start",

                                answer_id=
                                    answer_id,

                                question=
                                    question,

                                model=
                                    BACKEND_MODEL,

                                reasoning=
                                    "GPT-Live delegation",
                            )


                        current = (
                            state[
                                "answer_text"
                            ].get(
                                delegation_id,
                                "",
                            )
                        )

                        current += delta

                        state[
                            "answer_text"
                        ][
                            delegation_id
                        ] = current


                        await send(
                            "answer.delta",

                            answer_id=
                                answer_id,

                            text=
                                delta,

                            first_text_ms=
                                state[
                                    "first_text_ms"
                                ].get(
                                    delegation_id
                                ),
                        )

                        continue


                    # =============================================
                    # RESPONSE COMPLETED
                    # =============================================

                    if (
                        inner_kind
                        ==
                        "response.completed"
                    ):

                        answer_id = (
                            delegation_id
                        )

                        full = (
                            state[
                                "answer_text"
                            ].get(
                                delegation_id,
                                "",
                            )
                        )

                        started = (
                            state[
                                "delegation_started"
                            ].get(
                                delegation_id
                            )
                        )

                        total_ms = None

                        if started:

                            total_ms = round(
                                (
                                    time.monotonic()
                                    -
                                    started
                                )
                                *
                                1000
                            )


                        if full:

                            await send(
                                "answer.done",

                                answer_id=
                                    answer_id,

                                text=
                                    full,

                                first_text_ms=
                                    state[
                                        "first_text_ms"
                                    ].get(
                                        delegation_id
                                    ),

                                total_ms=
                                    total_ms,
                            )


                        # IMPORTANT:
                        #
                        # We deliberately remain PAUSED here.
                        #
                        # Do not automatically switch back to listening.
                        # The candidate may still be reading the answer.
                        await send(
                            "flow",
                            phase=
                                "paused",
                        )


                        await send(
                            "state",
                            message=(
                                "Answer ready · microphone paused · "
                                "tap Resume question listening for "
                                "the next question"
                            ),
                        )


                        print(
                            "GPT_LIVE_RESPONSE_DONE",
                            delegation_id,
                            total_ms,
                            flush=True,
                        )

                        continue


                    # =============================================
                    # RESPONSE FAILED
                    # =============================================

                    if inner_kind in (
                        "response.failed",
                        "response.incomplete",
                    ):

                        await send(
                            "error",

                            keep_capture=
                                False,

                            recoverable=
                                True,

                            message=(
                                "The delegated answer did not complete. "
                                "Use Retry or resume listening."
                            ),
                        )

                        continue


                # =================================================
                # IGNORE VOICE OUTPUT
                # =================================================

                if (
                    kind
                    ==
                    "session.output_audio.delta"
                ):
                    continue


                if (
                    kind
                    ==
                    "session.output_transcript.delta"
                ):
                    continue


                # =================================================
                # OPENAI SESSION CLOSED
                # =================================================

                if (
                    kind
                    ==
                    "session.closed"
                ):

                    print(
                        "GPT_LIVE_CLOSED",
                        flush=True,
                    )

                    return


        except asyncio.CancelledError:

            raise


        except Exception as error:

            print(
                "GPT_LIVE_READER_FAILED",
                type(
                    error
                ).__name__,
                flush=True,
            )

            with suppress(
                Exception
            ):

                await send(
                    "error",

                    keep_capture=
                        False,

                    recoverable=
                        True,

                    message=(
                        "GPT-Live disconnected. "
                        "Reconnect and start practice again."
                    ),
                )


    # ========================================================
    # EXISTING PHONE / G2 PROTOCOL
    # ========================================================

    try:

        # ====================================================
        # AUTHENTICATION
        # ====================================================

        hello = await asyncio.wait_for(
            ws.receive_json(),
            timeout=10,
        )

        expected = os.getenv(
            "APP_TOKEN",
            "",
        )

        supplied = hello.get(
            "token",
            "",
        )

        if (
            not expected
            or
            not isinstance(
                supplied,
                str,
            )
            or
            not hmac.compare_digest(
                expected,
                supplied,
            )
        ):

            await ws.close(
                code=1008,
                reason=
                    "Invalid app access token",
            )

            return


        if (
            hello.get(
                "type"
            )
            !=
            "auth"
        ):

            await ws.close(
                code=1008,
                reason=
                    "Authentication required",
            )

            return


        state[
            "authenticated"
        ] = True


        # Existing frontend expects natural_flow.
        await send(
            "ready",

            protocol=
                1,

            build=
                "0.3.1-gpt-live",

            features=[
                "continuous_questions",
                "display_settings",
                "speaker_follow",
                "model_selection",
                "coach_instructions",
                "natural_flow",
                "gpt_live_1",
                "pause_during_answer",
            ],
        )


        # ====================================================
        # MAIN PHONE / G2 LOOP
        # ====================================================

        while True:

            event = await ws.receive()

            if (
                event.get(
                    "type"
                )
                ==
                "websocket.disconnect"
            ):
                break


            # =================================================
            # RAW G2 MICROPHONE AUDIO
            # =================================================

            audio = event.get(
                "bytes"
            )

            if audio is not None:

                # Ignore microphone packets while paused.
                if (
                    not
                    state[
                        "listening"
                    ]
                    or
                    openai is None
                    or
                    not audio
                ):
                    continue


                # PCM16 must contain complete 2-byte samples.
                if (
                    len(
                        audio
                    )
                    %
                    2
                ):
                    audio = (
                        audio[:-1]
                    )


                if not audio:
                    continue


                # If Even identifies the wearer/candidate,
                # do not treat their speech as interviewer audio.
                if (
                    state[
                        "speaker"
                    ]
                    ==
                    "candidate"
                ):
                    continue


                encoded = (
                    base64.b64encode(
                        audio
                    )
                    .decode(
                        "ascii"
                    )
                )


                await openai.send(
                    json.dumps(
                        {
                            "type":
                                "session.input_audio.append",

                            "event_id":
                                "audio_"
                                + uuid.uuid4().hex,

                            "audio":
                                encoded,
                        }
                    )
                )

                continue


            # =================================================
            # JSON CONTROL MESSAGE
            # =================================================

            raw = event.get(
                "text",
                "",
            )

            if not raw:
                continue


            if len(
                raw
            ) > 16384:

                await ws.close(
                    code=1009
                )

                break


            try:

                message = json.loads(
                    raw
                )

            except json.JSONDecodeError:

                continue


            kind = message.get(
                "type"
            )


            # =================================================
            # PING
            # =================================================

            if kind == "ping":

                await send(
                    "pong"
                )

                continue


            # =================================================
            # SPEAKER ROLE ESTIMATE
            # =================================================

            if kind == "speaker":

                role = message.get(
                    "role"
                )

                if role in (
                    "candidate",
                    "interviewer",
                    "unknown",
                ):

                    state[
                        "speaker"
                    ] = role

                continue


            # =================================================
            # USER COACH INSTRUCTIONS
            # =================================================

            if (
                kind
                ==
                "coach.instructions"
            ):

                text = message.get(
                    "text",
                    "",
                )

                if not isinstance(
                    text,
                    str,
                ):

                    text = ""

                text = text[
                    :4000
                ]

                state[
                    "coach_instructions"
                ] = text


                await send(
                    "coach.instructions.saved",

                    active=
                        bool(
                            text.strip()
                        ),

                    characters=
                        len(
                            text
                        ),
                )

                continue


            # Voice-follow mode is currently handled on phone.
            if (
                kind
                ==
                "follow.mode"
            ):
                continue


            # =================================================
            # SETTINGS
            # =================================================

            if kind == "settings":

                await send(
                    "state",

                    message=(
                        "GPT-Live active · backend "
                        + BACKEND_MODEL
                    ),
                )

                continue


            # =================================================
            # START / RESUME LISTENING
            # =================================================

            if kind == "listen":

                await ensure_openai()

                # Clear old question transcript before listening
                # for the next interviewer question.
                state[
                    "transcript"
                ] = ""

                state[
                    "speaker"
                ] = (
                    state[
                        "speaker"
                    ]
                )

                await unmute_openai()

                state[
                    "listening"
                ] = True


                await send(
                    "capture",
                    active=True,
                )


                await send(
                    "flow",
                    phase=
                        "listening",
                )


                await send(
                    "state",

                    message=(
                        "GPT-Live listening · ask the next "
                        "complete question naturally"
                    ),
                )

                continue


            # =================================================
            # PAUSE MICROPHONE
            # =================================================

            if kind == "pause":

                state[
                    "listening"
                ] = False

                with suppress(
                    Exception
                ):
                    await mute_openai()


                await send(
                    "capture",
                    active=False,
                )


                await send(
                    "flow",
                    phase=
                        "paused",
                )

                continue


            # =================================================
            # FORCE ANSWER
            # =================================================

            if kind == "finish":

                await force_answer()

                continue


            # =================================================
            # RETRY ANSWER
            # =================================================

            if kind == "retry":

                await force_answer()

                continue


            # =================================================
            # CLEAR CAPTURED QUESTION
            # =================================================

            if (
                kind
                ==
                "clear.question"
            ):

                state[
                    "transcript"
                ] = ""


                await send(
                    "transcript.partial",
                    text="",
                )


                await send(
                    "flow",

                    phase=(
                        "listening"
                        if state[
                            "listening"
                        ]
                        else
                        "paused"
                    ),
                )

                continue


    except (
        WebSocketDisconnect,
        asyncio.TimeoutError,
    ):

        pass


    except Exception as error:

        print(
            "GPT_LIVE_G2_FAILED",
            type(
                error
            ).__name__,
            flush=True,
        )

        with suppress(
            Exception
        ):

            await send(
                "error",

                keep_capture=
                    False,

                message=(
                    "Live connection failed. "
                    "Stop and start practice again."
                ),
            )


    # ========================================================
    # CLEANUP
    # ========================================================

    finally:

        state[
            "listening"
        ] = False


        if openai is not None:

            with suppress(
                Exception
            ):

                await openai.send(
                    json.dumps(
                        {
                            "type":
                                "session.close",

                            "event_id":
                                "close_"
                                + uuid.uuid4().hex,
                        }
                    )
                )


            await asyncio.sleep(
                0.15
            )


        if reader:

            reader.cancel()

            with suppress(
                asyncio.CancelledError,
                Exception,
            ):

                await reader


        if openai is not None:

            with suppress(
                Exception
            ):

                await openai.close()


        with suppress(
            Exception
        ):

            await ws.close()


        print(
            "GPT_LIVE_G2_CLEANUP_COMPLETE",
            flush=True,
        )
