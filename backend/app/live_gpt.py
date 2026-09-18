"""
GPT-Live experimental backend for Interview Lens.

This module intentionally preserves the existing phone/G2 websocket
protocol so the Even Hub frontend does not need to be rebuilt.

Flow:

G2 microphone
    -> Render /ws/live
    -> GPT-Live-1
    -> semantic conversation understanding
    -> Responses delegation
    -> GPT-5.6 Terra/Luna
    -> answer.delta
    -> G2 display

Enable by setting:

OPENAI_LIVE_EXPERIMENT=1

The existing backend/app/live.py remains untouched and can be restored
simply by setting OPENAI_LIVE_EXPERIMENT=0.
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
# GPT-LIVE PROMPT
# ============================================================

LIVE_INSTRUCTIONS = """
You are the listening layer for a technical interview assistant.

Your most important job is to understand WHEN the interviewer has
finished asking the complete question.

The interviewer may:

- speak slowly
- pause for several seconds
- tell a long story before asking the question
- give multiple constraints
- correct something they said earlier
- ask several related subquestions
- describe a production incident before asking what should be done
- use technical terminology
- speak conversationally rather than using perfect grammar

DO NOT treat a normal pause as the end of the question.

DO NOT delegate while the interviewer is still giving the setup,
scenario, constraints, examples, corrections, or background.

Wait until the complete actionable request is clear.

For EVERY completed technical interview question, delegate the task
to the configured Responses backend.

Do not answer substantive technical interview questions yourself.
The backend agent provides the actual answer.

The application displays the backend answer as text on smart glasses,
so do not read the full backend answer aloud.

After delegation, return to listening for the next complete question.

If the speaker is merely thinking aloud, giving background, or has
not yet reached an actionable request, continue listening.

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
4. mention the important tradeoff or prevention step when relevant

Do not ignore the final clause of a long question.

TECHNICAL DEPTH

Answer at senior Data Engineer level.

Use accurate production concepts where relevant, including:

- BigQuery
- GCS
- Airflow
- Spark / PySpark
- Dataproc
- Dataflow
- Kafka / Pub/Sub
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

Do not force these technologies into an answer when they are not
relevant.

LENGTH

For a straightforward question:
roughly 70 to 130 words.

For a complex scenario or multipart question:
roughly 120 to 250 words.

Do not make the answer artificially short if the interviewer asks a
complex scenario.

SMART-GLASSES FORMAT

Use short paragraphs.

Avoid Markdown tables.

Avoid long headings.

Avoid unnecessary bullet lists.

Return only the answer that the candidate should say aloud.

PERSONAL EXPERIENCE

This experimental GPT-Live mode currently tests conversational
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
#
# Existing phone frontend calls this endpoint. We keep it so
# switching to GPT-Live does not break the model settings panel.
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
# SAFE DIAGNOSTICS
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

    # Official GPT-Live primary websocket.
    connection = await websockets.connect(
        "wss://api.openai.com/v1/live/sessions",

        additional_headers={
            "Authorization":
                f"Bearer {key}",
        },

        ping_interval=10,
        ping_timeout=10,
        close_timeout=5,

        # Keep enough room for provider events.
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

            # G2 gives us PCM16 mono at 16 kHz.
            #
            # GPT-Live officially supports 16 kHz PCM,
            # therefore we don't need the old 16 -> 24 kHz
            # audioop conversion.
            "audio": {
                "format": {
                    "type":
                        "audio/pcm",

                    "rate":
                        16000,
                },

                # GPT-Live is a voice model, although our
                # G2 experiment ignores returned audio.
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

            # We do not need stored recordings for this test.
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
# LIVE WEBSOCKET USED BY EXISTING EVEN APP
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

    # Shared state between the G2 websocket loop and
    # the GPT-Live event reader.
    state = {
        "authenticated":
            False,

        "listening":
            False,

        "muted":
            False,

        "transcript":
            "",

        # Transcript timestamps before this point belong
        # to a question we've already processed.
        "cut_ms":
            -1,

        "speaker":
            "unknown",

        "answer_text":
            {},

        "answer_started":
            set(),

        "question":
            {},

        "delegation_started":
            {},

        "coach_instructions":
            "",
    }

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


    # --------------------------------------------------------
    # Connect to GPT-Live only when microphone capture starts.
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Pause GPT-Live input.
    #
    # We use the official mute command rather than closing
    # the entire session, preserving conversational context.
    # --------------------------------------------------------

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

        state["muted"] = True


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

        state["muted"] = False


    # --------------------------------------------------------
    # Tell Responses backend to answer immediately.
    #
    # This is used by the existing
    # "Answer captured question" button.
    # --------------------------------------------------------

    async def force_answer():

        await ensure_openai()

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
            phase="generating",
        )


    # --------------------------------------------------------
    # GPT-Live event reader
    # --------------------------------------------------------

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


                # ------------------------------------------
                # Provider error
                # ------------------------------------------

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
                        keep_capture=True,
                        recoverable=True,
                        message=(
                            "GPT-Live reported an error. "
                            "Check Render logs for the safe diagnostic."
                        ),
                    )

                    continue


                # ------------------------------------------
                # GPT-Live user speech transcript
                #
                # These are fragments, NOT completed turns.
                # GPT-Live itself decides when the semantic
                # question is ready for delegation.
                # ------------------------------------------

                if (
                    kind
                    ==
                    "session.input_transcript.delta"
                ):

                    delta = event.get(
                        "delta",
                        "",
                    )

                    if not delta:
                        continue

                    end_ms = event.get(
                        "end_ms"
                    )

                    # Ignore a late transcript fragment from
                    # an already processed question.
                    if (
                        isinstance(
                            end_ms,
                            (int, float),
                        )
                        and
                        end_ms
                        <=
                        state["cut_ms"]
                    ):
                        continue

                    state[
                        "transcript"
                    ] += delta

                    # Prevent unbounded growth if somebody
                    # leaves the microphone open for hours.
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


                # ------------------------------------------
                # GPT-Live decided that there is now enough
                # semantic information to perform a task.
                #
                # THIS replaces the old:
                #
                # silence timeout
                #     ->
                # transcription completion
                #     ->
                # assess_turn()
                #
                # flow.
                # ------------------------------------------

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

                    # Clear the visible transcript for the
                    # next question. Late fragments belonging
                    # to the previous question are filtered
                    # using cut_ms above.
            # Clear transcript for the completed question.
                    state["transcript"] = ""

# IMPORTANT:
# Once a complete interview question has been detected,
# stop microphone capture while the candidate reads the answer.
#
# Otherwise the candidate's own voice becomes a new question
# and replaces the answer on the glasses.
state["listening"] = False

await send(
    "capture",
    active=False,
)

with suppress(Exception):
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
    phase="generating",
)

                    print(
                        "GPT_LIVE_DELEGATED",
                        delegation_id,
                        flush=True,
                    )

                    continue


                # ------------------------------------------
                # Responses backend events are wrapped
                # inside response.event.
                # ------------------------------------------

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


                    # --------------------------------------
                    # Stream backend text directly to G2.
                    # --------------------------------------

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

                        await send(
                            "answer.delta",

                            answer_id=
                                answer_id,

                            text=
                                delta,

                            first_text_ms=
                                first_text_ms,
                        )

                        continue


                    # --------------------------------------
                    # Backend response finished.
                    # --------------------------------------

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

                        # In case the Responses backend
                        # somehow completes without a delta,
                        # avoid wiping the existing lens frame.
                        if full:

                            await send(
                                "answer.done",

                                answer_id=
                                    answer_id,

                                text=
                                    full,

                                first_text_ms=
                                    None,

                                total_ms=
                                    total_ms,
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

                        print(
                            "GPT_LIVE_RESPONSE_DONE",
                            delegation_id,
                            total_ms,
                            flush=True,
                        )

                        continue


                    # --------------------------------------
                    # Responses backend failed.
                    # --------------------------------------

                    if inner_kind in (
                        "response.failed",
                        "response.incomplete",
                    ):

                        await send(
                            "error",
                            keep_capture=True,
                            recoverable=True,
                            message=(
                                "The delegated answer did not complete. "
                                "Repeat the question or use Retry."
                            ),
                        )

                        continue


                # ------------------------------------------
                # GPT-Live may produce voice output.
                #
                # We intentionally ignore returned audio
                # because Even G2 is being used as a
                # text-display assistant.
                # ------------------------------------------

                if (
                    kind
                    ==
                    "session.output_audio.delta"
                ):
                    continue


                # We also don't display the GPT-Live spoken
                # transcript because the delegated Responses
                # answer above is the richer answer we want
                # on the glasses.
                if (
                    kind
                    ==
                    "session.output_transcript.delta"
                ):
                    continue


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
                    keep_capture=False,
                    recoverable=True,
                    message=(
                        "GPT-Live disconnected. "
                        "Reconnect and start practice again."
                    ),
                )


    # ========================================================
    # EXISTING PHONE / G2 PROTOCOL
    # ========================================================

    try:

        # ----------------------------------------------------
        # Authentication
        # ----------------------------------------------------

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


        # Existing phone frontend specifically checks that
        # "natural_flow" exists.
        await send(
            "ready",

            protocol=
                1,

            build=
                "0.3.0-gpt-live",

            features=[
                "continuous_questions",
                "display_settings",
                "speaker_follow",
                "model_selection",
                "coach_instructions",
                "natural_flow",
                "gpt_live_1",
            ],
        )


        # ----------------------------------------------------
        # Main G2/phone receive loop
        # ----------------------------------------------------

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
            # RAW G2 AUDIO
            # =================================================

            audio = event.get(
                "bytes"
            )

            if audio is not None:

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


                # Existing G2 stream should already contain
                # complete signed 16-bit PCM samples.
                #
                # GPT-Live requires an even number of bytes.
                if (
                    len(
                        audio
                    )
                    %
                    2
                ):

                    # Dropping a single malformed final byte
                    # is safer than sending an invalid PCM
                    # sample to OpenAI.
                    audio = audio[:-1]


                if not audio:
                    continue


                # Optional speaker filter.
                #
                # If the phone explicitly knows this is the
                # candidate speaking, do not send that audio
                # to GPT-Live as a new interviewer question.
                #
                # Unknown/default audio is still forwarded.
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
            # JSON CONTROL FROM PHONE
            # =================================================

            raw = event.get(
                "text",
                "",
            )

            if not raw:
                continue


            if len(raw) > 16384:

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


            # ------------------------------------------------
            # Ping
            # ------------------------------------------------

            if kind == "ping":

                await send(
                    "pong"
                )

                continue


            # ------------------------------------------------
            # Speaker estimate from Even app
            # ------------------------------------------------

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


            # ------------------------------------------------
            # Coach instructions
            #
            # Stored so a later personalized version can feed
            # them into session.update.
            # ------------------------------------------------

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

                text = text[:4000]

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
                        len(text),
                )

                continue


            # Existing frontend sends this while switching
            # voice-follow display modes.
            if (
                kind
                ==
                "follow.mode"
            ):
                continue


            # ------------------------------------------------
            # SETTINGS
            #
            # For this first experiment we deliberately keep
            # GPT-Live backend model controlled by Render:
            #
            # OPENAI_LIVE_BACKEND_MODEL
            #
            # This avoids accidentally selecting a model that
            # is incompatible with Live Responses delegation.
            # ------------------------------------------------

            if kind == "settings":

                await send(
                    "state",
                    message=(
                        "GPT-Live test active · backend "
                        + BACKEND_MODEL
                    ),
                )

                continue


            # ------------------------------------------------
            # START / RESUME LISTENING
            # ------------------------------------------------

            if kind == "listen":

                await ensure_openai()

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
                        "GPT-Live listening — speak the "
                        "complete question naturally"
                    ),
                )

                continue


            # ------------------------------------------------
            # PAUSE
            # ------------------------------------------------

            if kind == "pause":

                state[
                    "listening"
                ] = False

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


            # ------------------------------------------------
            # FORCE QUESTION COMPLETION
            # ------------------------------------------------

            if kind == "finish":

                await force_answer()

                continue


            # ------------------------------------------------
            # RETRY
            #
            # response.create asks the configured Responses
            # backend to produce/continue work from current
            # Live conversational context.
            # ------------------------------------------------

            if kind == "retry":

                await force_answer()

                continue


            # ------------------------------------------------
            # CLEAR VISIBLE QUESTION
            # ------------------------------------------------

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
                keep_capture=False,
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

            # Official graceful Live session finalization.
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

            # Give OpenAI a brief chance to emit
            # session.closed before terminating socket.
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
