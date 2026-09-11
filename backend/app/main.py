from __future__ import annotations

import asyncio
import audioop
import base64
import io
import hmac
import json
import os
import time
import uuid

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    StreamingResponse,
)
from pypdf import PdfReader
from docx import Document

from .question import is_question
from .retrieval import search
from .storage import (
    active_profile,
    chunks_for,
    connect,
    snapshot,
)
from .providers import (
    answer_stream,
    openai_transcription_session,
)


MAX_UPLOAD = 8 * 1024 * 1024


# ============================================================
# AUTHENTICATION
# ============================================================

def auth(token: str | None):
    expected = os.getenv("APP_TOKEN")

    if not expected:
        raise HTTPException(
            status_code=503,
            detail="APP_TOKEN is not configured",
        )

    if not isinstance(token, str) or not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid access token",
        )


def auth_agent(
    authorization: str | None,
    x_app_token: str | None,
):
    """
    Even Agent Configuration normally sends the token as:

        Authorization: Bearer <token>

    We also accept X-App-Token so the endpoint can be tested
    manually using the same APP_TOKEN.
    """

    supplied = None

    if authorization:
        prefix = "Bearer "

        if authorization.startswith(prefix):
            supplied = authorization[len(prefix):].strip()

    if not supplied:
        supplied = x_app_token

    auth(supplied)


# ============================================================
# FILE EXTRACTION
# ============================================================

def extract(name: str, data: bytes) -> str:
    ext = name.lower().rsplit(".", 1)[-1]

    if ext in ("txt", "md", "csv"):
        return data.decode(
            "utf-8",
            errors="replace",
        )

    if ext == "pdf":
        return "\n".join(
            page.extract_text() or ""
            for page in PdfReader(
                io.BytesIO(data)
            ).pages
        )

    if ext == "docx":
        return "\n".join(
            p.text
            for p in Document(
                io.BytesIO(data)
            ).paragraphs
        )

    raise HTTPException(
        status_code=415,
        detail=(
            "Supported files: "
            "PDF, DOCX, TXT, MD, CSV"
        ),
    )


# ============================================================
# CHAT MESSAGE HELPERS
# ============================================================

def message_text(content) -> str:
    """
    Extract text from either:

    "content": "question"

    or OpenAI-style content arrays such as:

    "content": [
        {"type": "text", "text": "question"}
    ]
    """

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []

        for item in content:
            if not isinstance(item, dict):
                continue

            text = item.get("text")

            if isinstance(text, str):
                parts.append(text)

        return "\n".join(parts).strip()

    return ""


def latest_user_question(messages) -> str:
    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue

        if message.get("role") != "user":
            continue

        text = message_text(
            message.get("content")
        )

        if text:
            return text

    return ""


def interview_context(
    question: str,
):
    """
    Load the active profile and retrieve candidate evidence
    relevant to this interview question.
    """

    with connect() as db:
        profile = active_profile(db)

        if not profile:
            raise HTTPException(
                status_code=409,
                detail=(
                    "No active interview profile. "
                    "Open Interview Lens Manager and "
                    "select a profile first."
                ),
            )

        evidence = search(
            chunks_for(
                db,
                profile["id"],
            ),
            question,
        )

    grounded = "\n\n".join(
        f"[{chunk.source}] {chunk.text}"
        for chunk in evidence
    )

    if not grounded:
        grounded = (
            "No matching candidate evidence "
            "was uploaded."
        )

    return (
        profile,
        grounded,
    )


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Interview Lens",
    docs_url=None,
    redoc_url=None,
)

# Hub packages can use different WebView origins (including null). All manager
# routes still require an explicit app token; no ambient cookies are accepted.
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=False, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["X-App-Token", "Content-Type"])


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "Interview Lens",
        "agent_endpoint": "/v1/chat/completions",
        "live_protocol": 1,
    }


# ============================================================
# EVEN AI / OPENAI-COMPATIBLE AGENT ENDPOINT
# ============================================================

@app.post("/v1/chat/completions")
async def chat_completions(
    body: dict,
    authorization: str | None = Header(None),
    x_app_token: str | None = Header(None),
):
    """
    OpenAI-compatible Chat Completions endpoint for
    Even Realities Agent Configuration.

    Even configuration:

        Name:
        Interview Lens

        URL:
        https://<your-render-host>/v1/chat/completions

        Token:
        APP_TOKEN
    """

    auth_agent(
        authorization,
        x_app_token,
    )

    messages = body.get(
        "messages",
        []
    )

    question = latest_user_question(
        messages
    )

    if not question:
        raise HTTPException(
            status_code=400,
            detail=(
                "No user message was supplied."
            ),
        )

    profile, grounded = interview_context(
        question
    )

    print('LEGACY_DIAGNOSTIC', flush=True)

    print('LEGACY_DIAGNOSTIC', flush=True)

    # Retain recent context, excluding the newest user question already supplied.
    history = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") in ("user", "assistant"):
            text = message_text(message.get("content"))
            if text:
                history.append(f"{message['role']}: {text[:4000]}")
    if history and history[-1] == f"user: {question[:4000]}":
        history.pop()
    conversation_context = "\n".join(history[-12:])[-16000:]

    requested_stream = bool(
        body.get("stream", False)
    )

    completion_id = (
        "chatcmpl-"
        + uuid.uuid4().hex
    )

    created = int(
        time.time()
    )

    model = os.getenv(
        "OPENAI_MODEL",
        "gpt-5-mini",
    )


    # --------------------------------------------------------
    # STREAMING RESPONSE
    # --------------------------------------------------------

    if requested_stream:

        async def event_stream():
            try:
                first_chunk = {
                    "id": completion_id,
                    "object":
                        "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role":
                                    "assistant"
                            },
                            "finish_reason":
                                None,
                        }
                    ],
                }

                yield (
                    "data: "
                    + json.dumps(
                        first_chunk
                    )
                    + "\n\n"
                )

                full = ""

                async for delta in answer_stream(
                    question,
                    grounded,
                    conversation_context,
                ):
                    full += delta

                    chunk = {
                        "id":
                            completion_id,
                        "object":
                            "chat.completion.chunk",
                        "created":
                            created,
                        "model":
                            model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content":
                                        delta
                                },
                                "finish_reason":
                                    None,
                            }
                        ],
                    }

                    yield (
                        "data: "
                        + json.dumps(
                            chunk
                        )
                        + "\n\n"
                    )

                final_chunk = {
                    "id":
                        completion_id,
                    "object":
                        "chat.completion.chunk",
                    "created":
                        created,
                    "model":
                        model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason":
                                "stop",
                        }
                    ],
                }

                yield (
                    "data: "
                    + json.dumps(
                        final_chunk
                    )
                    + "\n\n"
                )

                yield "data: [DONE]\n\n"

                print('AGENT ANSWER COMPLETE:', flush=True)

            except Exception as e:
                print('AGENT STREAM ERROR:', flush=True)

                error_payload = {
                    "error": {
                        "message":
                            "Answer generation failed",
                        "type":
                            "server_error",
                    }
                }

                yield (
                    "data: "
                    + json.dumps(
                        error_payload
                    )
                    + "\n\n"
                )

                yield "data: [DONE]\n\n"


        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control":
                    "no-cache",
                "Connection":
                    "keep-alive",
                "X-Accel-Buffering":
                    "no",
            },
        )


    # --------------------------------------------------------
    # NORMAL NON-STREAMING RESPONSE
    # --------------------------------------------------------

    try:
        full = ""

        async for delta in answer_stream(
            question,
            grounded,
            conversation_context,
        ):
            full += delta

        print('AGENT ANSWER COMPLETE:', flush=True)

        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    except Exception as e:
        print('AGENT ANSWER ERROR:', flush=True)

        raise HTTPException(
            status_code=502,
            detail=(
                "OpenAI answer generation failed"
            ),
        )


# ============================================================
# MANAGER HOME PAGE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
def home():
    return HTMLResponse(
        MANAGER_HTML
    )


# ============================================================
# MANAGER API
# ============================================================

@app.get("/api/state")
def state(
    x_app_token: str | None =
        Header(None),
):
    auth(x_app_token)

    with connect() as db:
        return snapshot(db)


@app.post("/api/profiles")
def create_profile(
    name: str = Form(...),
    job_description: str = Form(""),
    x_app_token: str | None =
        Header(None),
):
    auth(x_app_token)

    pid = str(
        uuid.uuid4()
    )

    with connect() as db:
        db.execute(
            "UPDATE profiles SET active=0"
        )

        db.execute(
            "INSERT INTO profiles VALUES(?,?,?,?,?)",
            (
                pid,
                name.strip(),
                job_description.strip(),
                1,
                time.time(),
            ),
        )

        db.commit()

    return {
        "id": pid
    }


@app.post(
    "/api/profiles/{pid}/activate"
)
def activate(
    pid: str,
    x_app_token: str | None =
        Header(None),
):
    auth(x_app_token)

    with connect() as db:
        found = db.execute(
            """
            SELECT 1
            FROM profiles
            WHERE id=?
            """,
            (pid,),
        ).fetchone()

        if not found:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Profile not found"
                ),
            )

        db.execute(
            """
            UPDATE profiles
            SET active=(id=?)
            """,
            (pid,),
        )

        db.commit()

    return {
        "ok": True
    }


@app.post(
    "/api/profiles/{pid}/documents"
)
async def upload(
    pid: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    x_app_token: str | None =
        Header(None),
):
    auth(x_app_token)

    data = await file.read(
        MAX_UPLOAD + 1
    )

    if len(data) > MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail="File exceeds 8 MB",
        )

    if kind not in ("resume", "notes", "project", "responsibilities", "professional profile", "roles and responsibilities", "project notes", "prep notes", "project details", "other evidence", "core_profile"):
        raise HTTPException(status_code=422, detail="Unsupported document type")
    try:
        text = extract(file.filename or "upload.txt", data).strip()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read this file. Try a text PDF, DOCX or TXT file.")

    if not text:
        raise HTTPException(
            status_code=422,
            detail=(
                "No readable text found"
            ),
        )

    if kind == "core_profile" and len(text) > 4000:
        raise HTTPException(status_code=422, detail="Core profile must be 4,000 characters or fewer. Upload longer material as Prep notes.")

    did = str(
        uuid.uuid4()
    )

    with connect() as db:
        found = db.execute(
            """
            SELECT 1
            FROM profiles
            WHERE id=?
            """,
            (pid,),
        ).fetchone()

        if not found:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Profile not found"
                ),
            )

        if kind == "core_profile":
            db.execute("DELETE FROM documents WHERE profile_id=? AND kind='core_profile'", (pid,))

        db.execute(
            """
            INSERT INTO documents
            VALUES(?,?,?,?,?,?)
            """,
            (
                did,
                pid,
                file.filename,
                kind,
                text,
                time.time(),
            ),
        )

        db.commit()

    return {
        "id": did,
        "characters": len(text),
    }


@app.delete(
    "/api/documents/{did}"
)
def delete_document(
    did: str,
    x_app_token: str | None =
        Header(None),
):
    auth(x_app_token)

    with connect() as db:
        db.execute(
            """
            DELETE FROM documents
            WHERE id=?
            """,
            (did,),
        )

        db.commit()

    return {
        "ok": True
    }


# ============================================================
# EXISTING G2 WEBSOCKET
# ============================================================

@app.websocket("/ws/glasses")
async def glasses(
    ws: WebSocket
):
    expected_token = os.getenv(
        "APP_TOKEN"
    )

    supplied_token = (
        ws.query_params.get(
            "token"
        )
    )

    if (
        not expected_token
        or supplied_token
        != expected_token
    ):
        await ws.close(
            code=1008
        )
        return

    await ws.accept()

    print(
        "G2 CLIENT CONNECTED",
        flush=True,
    )

    transcription = None
    stt_task = None
    generate_task = None

    sent = {}
    acks = []

    rate_state = None

    try:
        # --------------------------------------------------
        # Load active profile
        # --------------------------------------------------

        with connect() as db:
            p = active_profile(db)

            if not p:
                await ws.send_json(
                    {
                        "type": "error",
                        "message":
                            "No active interview profile",
                    }
                )

                await ws.close(
                    code=1011
                )
                return

            profile_id = p["id"]
            profile_name = p["name"]


        await ws.send_json(
            {
                "type": "ready",
                "profile":
                    profile_name,
            }
        )

        print('LEGACY_DIAGNOSTIC', flush=True)


        # --------------------------------------------------
        # OpenAI realtime transcription
        # --------------------------------------------------

        print(
            "OPENING OPENAI "
            "TRANSCRIPTION SESSION",
            flush=True,
        )

        transcription = (
            await
            openai_transcription_session()
        )

        print(
            "OPENAI TRANSCRIPTION "
            "CONNECTED",
            flush=True,
        )

        await ws.send_json(
            {
                "type": "state",
                "state": "listening",
            }
        )

        started = (
            time.perf_counter()
        )


        # --------------------------------------------------
        # Answer generation
        # --------------------------------------------------

        async def generate(
            question: str,
            stt_ms: float,
        ):
            t0 = (
                time.perf_counter()
            )

            try:
                await ws.send_json(
                    {
                        "type": "state",
                        "state":
                            "question detected",
                        "transcript":
                            question,
                    }
                )

                print('LEGACY_DIAGNOSTIC', flush=True)

                with connect() as db:
                    evidence = search(
                        chunks_for(
                            db,
                            profile_id,
                        ),
                        question,
                    )

                retrieval_ms = (
                    time.perf_counter()
                    - t0
                ) * 1000

                grounded = (
                    "\n\n".join(
                        f"[{c.source}] "
                        f"{c.text}"
                        for c in evidence
                    )
                )

                if not grounded:
                    grounded = (
                        "No matching candidate "
                        "evidence was uploaded."
                    )

                full = ""
                first = None

                answer_id = str(
                    uuid.uuid4()
                )

                seq = 0

                async for delta in answer_stream(
                    question,
                    grounded,
                ):
                    if first is None:
                        first = (
                            time.perf_counter()
                        )

                    full += delta
                    seq += 1

                    sent[
                        (
                            answer_id,
                            seq,
                        )
                    ] = (
                        time.perf_counter()
                    )

                    await ws.send_json(
                        {
                            "type":
                                "answer.delta",
                            "text":
                                delta,
                            "first":
                                len(full)
                                == len(delta),
                            "answer_id":
                                answer_id,
                            "seq":
                                seq,
                        }
                    )

                await asyncio.sleep(
                    0.08
                )

                total = (
                    time.perf_counter()
                    - t0
                ) * 1000

                mine = [
                    a
                    for a in acks
                    if a[0]
                    == answer_id
                ]

                if mine:
                    transport_ms = round(
                        sum(
                            a[2]
                            for a in mine
                        )
                        / len(mine)
                        / 2
                    )

                    display_ms = round(
                        sum(
                            a[3]
                            for a in mine
                        )
                        / len(mine)
                    )
                else:
                    transport_ms = None
                    display_ms = None

                first_token_ms = (
                    (
                        first - t0
                    ) * 1000
                    if first
                    else total
                )

                metrics = {
                    "stt_ms":
                        round(stt_ms),
                    "retrieval_ms":
                        round(
                            retrieval_ms
                        ),
                    "model_first_token_ms":
                        round(
                            first_token_ms
                        ),
                    "transport_ms":
                        transport_ms,
                    "display_estimate_ms":
                        display_ms,
                    "total_ms":
                        round(total),
                }

                await ws.send_json(
                    {
                        "type":
                            "answer.done",
                        "text":
                            full,
                        "metrics":
                            metrics,
                    }
                )

                print('LEGACY_DIAGNOSTIC', flush=True)

                with connect() as db:
                    db.execute(
                        """
                        INSERT INTO metrics(
                            profile_id,
                            created_at,
                            question,
                            stt_ms,
                            retrieval_ms,
                            model_first_token_ms,
                            transport_ms,
                            display_estimate_ms,
                            total_ms
                        )
                        VALUES(
                            ?,?,?,?,?,?,?,?,?
                        )
                        """,
                        (
                            profile_id,
                            time.time(),
                            question,
                            metrics[
                                "stt_ms"
                            ],
                            metrics[
                                "retrieval_ms"
                            ],
                            metrics[
                                "model_first_token_ms"
                            ],
                            metrics[
                                "transport_ms"
                            ],
                            metrics[
                                "display_estimate_ms"
                            ],
                            metrics[
                                "total_ms"
                            ],
                        ),
                    )

                    db.commit()

                await ws.send_json(
                    {
                        "type": "state",
                        "state":
                            "listening",
                    }
                )

            except asyncio.CancelledError:
                print(
                    "ANSWER GENERATION "
                    "CANCELLED",
                    flush=True,
                )

                raise

            except Exception as e:
                print('ANSWER GENERATION ERROR:', flush=True)

                try:
                    await ws.send_json(
                        {
                            "type":
                                "error",
                            "message":
                                "Answer generation failed",
                        }
                    )

                except Exception:
                    pass


        # --------------------------------------------------
        # OpenAI STT event reader
        # --------------------------------------------------

        async def receive_stt():
            nonlocal started
            nonlocal generate_task

            try:
                async for raw in transcription:
                    msg = json.loads(
                        raw
                    )

                    event_type = (
                        msg.get("type")
                    )

                    if event_type == "error":
                        print('OPENAI REALTIME ERROR:', flush=True)

                        continue

                    if (
                        event_type
                        ==
                        "input_audio_buffer."
                        "speech_started"
                    ):
                        started = (
                            time.perf_counter()
                        )

                        try:
                            await ws.send_json(
                                {
                                    "type":
                                        "state",
                                    "state":
                                        "hearing speech",
                                }
                            )

                        except Exception:
                            return

                        continue

                    if (
                        event_type
                        !=
                        "conversation.item."
                        "input_audio_transcription."
                        "completed"
                    ):
                        continue

                    utterance = (
                        msg.get(
                            "transcript",
                            "",
                        )
                        .strip()
                    )

                    if not utterance:
                        continue

                    print('LEGACY_DIAGNOSTIC', flush=True)

                    if not is_question(
                        utterance
                    ):
                        try:
                            await ws.send_json(
                                {
                                    "type":
                                        "state",
                                    "state":
                                        "listening",
                                }
                            )

                        except Exception:
                            return

                        started = (
                            time.perf_counter()
                        )

                        continue

                    stt_ms = (
                        time.perf_counter()
                        - started
                    ) * 1000

                    if (
                        generate_task
                        and
                        not generate_task.done()
                    ):
                        generate_task.cancel()

                    generate_task = (
                        asyncio.create_task(
                            generate(
                                utterance,
                                stt_ms,
                            )
                        )
                    )

                    started = (
                        time.perf_counter()
                    )

            except asyncio.CancelledError:
                raise

            except Exception as e:
                print('STT RECEIVE ERROR:', flush=True)

                raise


        # --------------------------------------------------
        # Start STT reader
        # --------------------------------------------------

        stt_task = (
            asyncio.create_task(
                receive_stt()
            )
        )

        def log_stt_result(
            task
        ):
            try:
                task.result()

            except asyncio.CancelledError:
                pass

            except Exception as e:
                print('STT TASK ERROR:', flush=True)

        stt_task.add_done_callback(
            log_stt_result
        )


        # --------------------------------------------------
        # Receive G2 audio/control
        # --------------------------------------------------

        while True:
            event = await ws.receive()

            event_type = (
                event.get("type")
            )

            if (
                event_type
                ==
                "websocket.disconnect"
            ):
                print('G2 DISCONNECT EVENT:', flush=True)

                break


            # ----------------------------------------------
            # Binary G2 microphone audio
            # ----------------------------------------------

            audio_bytes = (
                event.get("bytes")
            )

            if audio_bytes:
                try:
                    (
                        pcm24,
                        rate_state,
                    ) = audioop.ratecv(
                        audio_bytes,
                        2,
                        1,
                        16000,
                        24000,
                        rate_state,
                    )

                    encoded = (
                        base64.b64encode(
                            pcm24
                        )
                        .decode("ascii")
                    )

                    await transcription.send(
                        json.dumps(
                            {
                                "type":
                                    "input_audio_buffer.append",
                                "audio":
                                    encoded,
                            }
                        )
                    )

                except Exception as e:
                    print('AUDIO FORWARD ERROR:', flush=True)

                    raise

                continue


            # ----------------------------------------------
            # JSON messages from G2
            # ----------------------------------------------

            text = event.get(
                "text"
            )

            if text:
                try:
                    msg = json.loads(
                        text
                    )

                except json.JSONDecodeError:
                    print('INVALID CLIENT JSON:', flush=True)

                    continue

                msg_type = (
                    msg.get("type")
                )

                if (
                    msg_type
                    == "display.ack"
                ):
                    key = (
                        msg.get(
                            "answer_id"
                        ),
                        msg.get("seq"),
                    )

                    then = sent.pop(
                        key,
                        None,
                    )

                    if then:
                        acks.append(
                            (
                                key[0],
                                key[1],
                                (
                                    time.perf_counter()
                                    - then
                                )
                                * 1000,
                                float(
                                    msg.get(
                                        "display_call_ms",
                                        0,
                                    )
                                ),
                            )
                        )

                elif (
                    msg_type == "ping"
                ):
                    await ws.send_json(
                        {
                            "type":
                                "pong",
                            "time":
                                time.time(),
                        }
                    )


    except WebSocketDisconnect:
        print(
            "G2 CLIENT DISCONNECTED",
            flush=True,
        )

    except RuntimeError as e:
        print('WEBSOCKET RUNTIME ERROR:', flush=True)

    except Exception as e:
        print('GLASSES WEBSOCKET ERROR:', flush=True)

        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message":
                        str(e),
                }
            )

        except Exception:
            pass

    finally:
        if (
            generate_task
            and
            not generate_task.done()
        ):
            generate_task.cancel()

        if (
            stt_task
            and
            not stt_task.done()
        ):
            stt_task.cancel()

        if stt_task:
            try:
                await stt_task

            except asyncio.CancelledError:
                pass

            except Exception:
                pass

        if transcription:
            try:
                await transcription.close()

            except Exception:
                pass

        print(
            "G2 SESSION CLEANUP COMPLETE",
            flush=True,
        )


# ============================================================
# INTERVIEW LENS MANAGER HTML
# ============================================================

MANAGER_HTML = '''
<!doctype html>

<html>

<head>

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>
Interview Lens Manager
</title>

<style>

body{
    font:16px system-ui;
    background:#f1f5f1;
    color:#18251b;
    margin:0
}

.wrap{
    max-width:760px;
    margin:auto;
    padding:20px
}

.card{
    background:#fff;
    border:1px solid #dce5dc;
    border-radius:16px;
    padding:18px;
    margin:14px 0
}

input,
textarea,
select,
button{
    font:inherit;
    width:100%;
    padding:11px;
    margin:6px 0;
    box-sizing:border-box;
    border:1px solid #bdc9bd;
    border-radius:9px
}

button{
    background:#19492b;
    color:#fff;
    font-weight:700
}

.row{
    display:flex;
    gap:8px
}

.muted{
    color:#68746a;
    font-size:14px
}

.pill{
    display:inline-block;
    background:#e5f2e8;
    padding:4px 8px;
    border-radius:9px;
    margin:3px
}

pre{
    white-space:pre-wrap
}

</style>

</head>

<body>

<div class="wrap">

<h1>
Interview Lens
</h1>

<p class="muted">
Private profile and latency manager
</p>


<div class="card">

<label>
Access token
</label>

<input
    id="token"
    type="password"
>

<button onclick="load()">
Unlock
</button>

<div id="msg"></div>

</div>


<div id="app"></div>

</div>


<script>

const $ = s =>
    document.querySelector(s)

const esc = s =>
    String(s ?? '').replace(
        /[&<>]/g,
        c => ({
            '&':'&amp;',
            '<':'&lt;',
            '>':'&gt;'
        }[c])
    )

let state


async function api(
    path,
    opts={}
) {

    opts.headers = {
        ...(opts.headers || {}),
        'X-App-Token':
            $('#token').value
    }

    const r =
        await fetch(
            path,
            opts
        )

    if (!r.ok)
        throw Error(
            await r.text()
        )

    return r.json()
}


async function load() {

    try {

        state =
            await api(
                '/api/state'
            )

        render()

        $('#msg').textContent =
            'Unlocked'

    } catch(e) {

        $('#msg').textContent =
            e.message
    }
}


function render() {

    const active =
        state.profiles.find(
            p => p.active
        )
        ||
        state.profiles[0]

    if (!active) {

        $('#app').innerHTML =
        `
        <div class="card">

        <h2>
        Interview profiles
        </h2>

        <h3>
        New profile
        </h3>

        <form
            onsubmit="createP(event)"
        >

        <input
            name="name"
            placeholder="Role / company"
            required
        >

        <textarea
            name="job_description"
            rows="7"
            placeholder="Paste the target job description"
        ></textarea>

        <button>
        Create & select
        </button>

        </form>

        </div>
        `

        return
    }


    $('#app').innerHTML =
    `
    <div class="card">

    <h2>
    Interview profiles
    </h2>

    ${
        state.profiles.map(
            p =>
            `
            <button
                onclick="activate('${p.id}')"
            >
            ${p.active ? '✓ ' : ''}
            ${esc(p.name)}
            </button>
            `
        ).join('')
    }

    <h3>
    New profile
    </h3>

    <form
        onsubmit="createP(event)"
    >

    <input
        name="name"
        placeholder="Role / company"
        required
    >

    <textarea
        name="job_description"
        rows="7"
        placeholder="Paste the target job description"
    ></textarea>

    <button>
    Create & select
    </button>

    </form>

    </div>


    <div class="card">

    <h2>
    Materials · ${esc(active.name)}
    </h2>

    <form
        onsubmit="upload(
            event,
            '${active.id}'
        )"
    >

    <select name="kind">

    <option>
    resume
    </option>

    <option>
    professional profile
    </option>

    <option>
    roles and responsibilities
    </option>

    <option>
    project details
    </option>

    <option>
    other evidence
    </option>

    </select>

    <input
        name="file"
        type="file"
        accept=".pdf,.docx,.txt,.md,.csv"
        required
    >

    <button>
    Upload
    </button>

    </form>

    ${
        active.documents.map(
            d =>
            `
            <div class="pill">

            ${esc(d.kind)}
            ·
            ${esc(d.name)}

            <a
                href="#"
                onclick="del('${d.id}')"
            >
            ×
            </a>

            </div>
            `
        ).join('')
        ||
        `
        <p class="muted">
        Upload truthful candidate evidence
        before an interview.
        </p>
        `
    }

    </div>


    <div class="card">

    <h2>
    Measured latency
    </h2>

    <p class="muted">
    STT includes speech + endpointing.
    Transport is half the phone
    acknowledgement round trip;
    display is SDK update-call time,
    not a photons-on-lens guarantee.
    </p>

    ${
        state.metrics.slice(
            0,
            10
        ).map(
            m =>
            `
            <p>

            <b>
            ${m.total_ms} ms generation
            </b>

            · STT ${m.stt_ms}

            · retrieval
            ${m.retrieval_ms}

            · first token
            ${m.model_first_token_ms}

            · transport
            ${m.transport_ms ?? 'n/a'}

            · display call
            ${m.display_estimate_ms ?? 'n/a'}

            <br>

            <span class="muted">
            ${esc(m.question)}
            </span>

            </p>
            `
        ).join('')
        ||
        `
        <p>
        No live measurements yet.
        </p>
        `
    }

    </div>
    `
}


async function createP(e) {

    e.preventDefault()

    await api(
        '/api/profiles',
        {
            method:'POST',
            body:
                new FormData(
                    e.target
                )
        }
    )

    load()
}


async function activate(id) {

    await api(
        '/api/profiles/'
        + id
        + '/activate',
        {
            method:'POST'
        }
    )

    load()
}


async function upload(
    e,
    id
) {

    e.preventDefault()

    await api(
        '/api/profiles/'
        + id
        + '/documents',
        {
            method:'POST',
            body:
                new FormData(
                    e.target
                )
        }
    )

    load()
}


async function del(id) {

    await api(
        '/api/documents/'
        + id,
        {
            method:'DELETE'
        }
    )

    load()
}

</script>

</body>

</html>
'''



from .live import router as live_router
app.include_router(live_router)
