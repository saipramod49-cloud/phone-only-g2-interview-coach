from __future__ import annotations

import asyncio
import audioop
import base64
import io
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
from fastapi.responses import HTMLResponse
from pypdf import PdfReader
from docx import Document

from .question import is_question
from .retrieval import search
from .storage import active_profile, chunks_for, connect, snapshot
from .providers import answer_stream, openai_transcription_session


MAX_UPLOAD = 8 * 1024 * 1024


def auth(token: str | None):
    expected = os.getenv("APP_TOKEN")

    if not expected:
        raise HTTPException(
            status_code=503,
            detail="APP_TOKEN is not configured",
        )

    if token != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid access token",
        )


def extract(name: str, data: bytes) -> str:
    ext = name.lower().rsplit(".", 1)[-1]

    if ext in ("txt", "md", "csv"):
        return data.decode("utf-8", errors="replace")

    if ext == "pdf":
        return "\n".join(
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(data)).pages
        )

    if ext == "docx":
        return "\n".join(
            p.text
            for p in Document(io.BytesIO(data)).paragraphs
        )

    raise HTTPException(
        status_code=415,
        detail="Supported files: PDF, DOCX, TXT, MD, CSV",
    )


app = FastAPI(
    title="Interview Lens",
    docs_url=None,
    redoc_url=None,
)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(MANAGER_HTML)


@app.get("/api/state")
def state(x_app_token: str | None = Header(None)):
    auth(x_app_token)

    with connect() as db:
        return snapshot(db)


@app.post("/api/profiles")
def create_profile(
    name: str = Form(...),
    job_description: str = Form(""),
    x_app_token: str | None = Header(None),
):
    auth(x_app_token)

    pid = str(uuid.uuid4())

    with connect() as db:
        db.execute("UPDATE profiles SET active=0")

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

    return {"id": pid}


@app.post("/api/profiles/{pid}/activate")
def activate(
    pid: str,
    x_app_token: str | None = Header(None),
):
    auth(x_app_token)

    with connect() as db:
        found = db.execute(
            "SELECT 1 FROM profiles WHERE id=?",
            (pid,),
        ).fetchone()

        if not found:
            raise HTTPException(
                status_code=404,
                detail="Profile not found",
            )

        db.execute(
            "UPDATE profiles SET active=(id=?)",
            (pid,),
        )

        db.commit()

    return {"ok": True}


@app.post("/api/profiles/{pid}/documents")
async def upload(
    pid: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    x_app_token: str | None = Header(None),
):
    auth(x_app_token)

    data = await file.read(MAX_UPLOAD + 1)

    if len(data) > MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail="File exceeds 8 MB",
        )

    text = extract(
        file.filename or "upload.txt",
        data,
    ).strip()

    if not text:
        raise HTTPException(
            status_code=422,
            detail="No readable text found",
        )

    did = str(uuid.uuid4())

    with connect() as db:
        found = db.execute(
            "SELECT 1 FROM profiles WHERE id=?",
            (pid,),
        ).fetchone()

        if not found:
            raise HTTPException(
                status_code=404,
                detail="Profile not found",
            )

        db.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?)",
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


@app.delete("/api/documents/{did}")
def delete_document(
    did: str,
    x_app_token: str | None = Header(None),
):
    auth(x_app_token)

    with connect() as db:
        db.execute(
            "DELETE FROM documents WHERE id=?",
            (did,),
        )

        db.commit()

    return {"ok": True}


@app.websocket("/ws/glasses")
async def glasses(ws: WebSocket):
    expected_token = os.getenv("APP_TOKEN")
    supplied_token = ws.query_params.get("token")

    if not expected_token or supplied_token != expected_token:
        await ws.close(code=1008)
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
        # Load active interview profile
        # --------------------------------------------------

        with connect() as db:
            p = active_profile(db)

            if not p:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": "No active interview profile",
                    }
                )

                await ws.close(code=1011)
                return

            profile_id = p["id"]
            profile_name = p["name"]

        # --------------------------------------------------
        # Tell G2 client backend is ready
        # --------------------------------------------------

        await ws.send_json(
            {
                "type": "ready",
                "profile": profile_name,
            }
        )

        print(
            f"ACTIVE PROFILE: {profile_name}",
            flush=True,
        )

        # --------------------------------------------------
        # Open OpenAI realtime transcription
        # --------------------------------------------------

        print(
            "OPENING OPENAI TRANSCRIPTION SESSION",
            flush=True,
        )

        transcription = await openai_transcription_session()

        print(
            "OPENAI TRANSCRIPTION CONNECTED",
            flush=True,
        )

        await ws.send_json(
            {
                "type": "state",
                "state": "listening",
            }
        )

        started = time.perf_counter()

        # --------------------------------------------------
        # Generate answer
        # --------------------------------------------------

        async def generate(
            question: str,
            stt_ms: float,
        ):
            t0 = time.perf_counter()

            try:
                await ws.send_json(
                    {
                        "type": "state",
                        "state": "question detected",
                        "transcript": question,
                    }
                )

                print(
                    f"QUESTION: {question}",
                    flush=True,
                )

                with connect() as db:
                    evidence = search(
                        chunks_for(db, profile_id),
                        question,
                    )

                retrieval_ms = (
                    time.perf_counter() - t0
                ) * 1000

                grounded = "\n\n".join(
                    f"[{c.source}] {c.text}"
                    for c in evidence
                )

                if not grounded:
                    grounded = (
                        "No matching candidate evidence "
                        "was uploaded."
                    )

                full = ""
                first = None

                answer_id = str(uuid.uuid4())
                seq = 0

                async for delta in answer_stream(
                    question,
                    grounded,
                ):
                    if first is None:
                        first = time.perf_counter()

                    full += delta
                    seq += 1

                    sent[
                        (answer_id, seq)
                    ] = time.perf_counter()

                    await ws.send_json(
                        {
                            "type": "answer.delta",
                            "text": delta,
                            "first": len(full) == len(delta),
                            "answer_id": answer_id,
                            "seq": seq,
                        }
                    )

                await asyncio.sleep(0.08)

                total = (
                    time.perf_counter() - t0
                ) * 1000

                mine = [
                    a
                    for a in acks
                    if a[0] == answer_id
                ]

                if mine:
                    transport_ms = round(
                        sum(a[2] for a in mine)
                        / len(mine)
                        / 2
                    )

                    display_ms = round(
                        sum(a[3] for a in mine)
                        / len(mine)
                    )
                else:
                    transport_ms = None
                    display_ms = None

                first_token_ms = (
                    (first - t0) * 1000
                    if first
                    else total
                )

                metrics = {
                    "stt_ms": round(stt_ms),
                    "retrieval_ms": round(retrieval_ms),
                    "model_first_token_ms": round(
                        first_token_ms
                    ),
                    "transport_ms": transport_ms,
                    "display_estimate_ms": display_ms,
                    "total_ms": round(total),
                }

                await ws.send_json(
                    {
                        "type": "answer.done",
                        "text": full,
                        "metrics": metrics,
                    }
                )

                print(
                    f"ANSWER COMPLETE: {metrics}",
                    flush=True,
                )

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
                        VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            profile_id,
                            time.time(),
                            question,
                            metrics["stt_ms"],
                            metrics["retrieval_ms"],
                            metrics[
                                "model_first_token_ms"
                            ],
                            metrics["transport_ms"],
                            metrics[
                                "display_estimate_ms"
                            ],
                            metrics["total_ms"],
                        ),
                    )

                    db.commit()

                await ws.send_json(
                    {
                        "type": "state",
                        "state": "listening",
                    }
                )

            except asyncio.CancelledError:
                print(
                    "ANSWER GENERATION CANCELLED",
                    flush=True,
                )
                raise

            except Exception as e:
                print(
                    "ANSWER GENERATION ERROR:",
                    repr(e),
                    flush=True,
                )

                try:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "Answer generation failed",
                        }
                    )
                except Exception:
                    pass

        # --------------------------------------------------
        # Receive OpenAI transcription events
        # --------------------------------------------------

        async def receive_stt():
            nonlocal started
            nonlocal generate_task

            try:
                async for raw in transcription:
                    msg = json.loads(raw)
                    event_type = msg.get("type")

                    if event_type == "error":
                        print(
                            "OPENAI REALTIME ERROR:",
                            json.dumps(msg),
                            flush=True,
                        )
                        continue

                    if (
                        event_type
                        == "input_audio_buffer.speech_started"
                    ):
                        started = time.perf_counter()

                        try:
                            await ws.send_json(
                                {
                                    "type": "state",
                                    "state": "hearing speech",
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
                        msg.get("transcript", "")
                        .strip()
                    )

                    if not utterance:
                        continue

                    print(
                        f"TRANSCRIPT: {utterance}",
                        flush=True,
                    )

                    if not is_question(utterance):
                        try:
                            await ws.send_json(
                                {
                                    "type": "state",
                                    "state": "listening",
                                }
                            )
                        except Exception:
                            return

                        started = time.perf_counter()
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

                    generate_task = asyncio.create_task(
                        generate(
                            utterance,
                            stt_ms,
                        )
                    )

                    started = time.perf_counter()

            except asyncio.CancelledError:
                raise

            except Exception as e:
                print(
                    "STT RECEIVE ERROR:",
                    repr(e),
                    flush=True,
                )

                raise

        # --------------------------------------------------
        # Start background STT reader
        # --------------------------------------------------

        stt_task = asyncio.create_task(
            receive_stt()
        )

        def log_stt_result(task):
            try:
                task.result()

            except asyncio.CancelledError:
                pass

            except Exception as e:
                print(
                    "STT TASK ERROR:",
                    repr(e),
                    flush=True,
                )

        stt_task.add_done_callback(
            log_stt_result
        )

        # --------------------------------------------------
        # Receive audio / control messages from Even G2
        # --------------------------------------------------

        while True:
            event = await ws.receive()

            event_type = event.get("type")

            # FastAPI returns a websocket.disconnect event
            # before raising WebSocketDisconnect.
            # Do not call receive() again after this.
            if event_type == "websocket.disconnect":
                print(
                    "G2 DISCONNECT EVENT:",
                    event.get("code"),
                    flush=True,
                )
                break

            # ----------------------------------------------
            # Binary microphone audio
            # ----------------------------------------------

            audio_bytes = event.get("bytes")

            if audio_bytes:
                try:
                    pcm24, rate_state = audioop.ratecv(
                        audio_bytes,
                        2,
                        1,
                        16000,
                        24000,
                        rate_state,
                    )

                    encoded = base64.b64encode(
                        pcm24
                    ).decode("ascii")

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
                    print(
                        "AUDIO FORWARD ERROR:",
                        repr(e),
                        flush=True,
                    )
                    raise

                continue

            # ----------------------------------------------
            # JSON messages from G2 client
            # ----------------------------------------------

            text = event.get("text")

            if text:
                try:
                    msg = json.loads(text)

                except json.JSONDecodeError:
                    print(
                        "INVALID CLIENT JSON:",
                        text,
                        flush=True,
                    )
                    continue

                msg_type = msg.get("type")

                if msg_type == "display.ack":
                    key = (
                        msg.get("answer_id"),
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

                elif msg_type == "ping":
                    await ws.send_json(
                        {
                            "type": "pong",
                            "time": time.time(),
                        }
                    )

    except WebSocketDisconnect:
        print(
            "G2 CLIENT DISCONNECTED",
            flush=True,
        )

    except RuntimeError as e:
        print(
            "WEBSOCKET RUNTIME ERROR:",
            repr(e),
            flush=True,
        )

    except Exception as e:
        print(
            "GLASSES WEBSOCKET ERROR:",
            repr(e),
            flush=True,
        )

        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": str(e),
                }
            )
        except Exception:
            pass

    finally:
        # --------------------------------------------------
        # Cleanup
        # --------------------------------------------------

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


MANAGER_HTML = '''
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Interview Lens Manager</title>

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

<h1>Interview Lens</h1>

<p class="muted">
Private profile and latency manager
</p>

<div class="card">

<label>Access token</label>

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

async function api(path, opts={}) {

    opts.headers = {
        ...(opts.headers || {}),
        'X-App-Token':
            $('#token').value
    }

    const r =
        await fetch(path, opts)

    if (!r.ok)
        throw Error(
            await r.text()
        )

    return r.json()
}

async function load() {

    try {

        state =
            await api('/api/state')

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

        <h2>Interview profiles</h2>

        <h3>New profile</h3>

        <form onsubmit="createP(event)">

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

    <h2>Interview profiles</h2>

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

    <h3>New profile</h3>

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

async function upload(e,id) {

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
