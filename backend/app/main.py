from __future__ import annotations
import audioop, base64, io, json, os, time, uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pypdf import PdfReader
from docx import Document
from .question import is_question
from .retrieval import search
from .storage import active_profile, chunks_for, connect, snapshot
from .providers import answer_stream, openai_transcription_session

MAX_UPLOAD=8*1024*1024

def auth(token: str | None):
    expected=os.getenv("APP_TOKEN")
    if not expected: raise HTTPException(503,"APP_TOKEN is not configured")
    if token != expected: raise HTTPException(401,"Invalid access token")

def extract(name: str, data: bytes) -> str:
    ext=name.lower().rsplit(".",1)[-1]
    if ext in ("txt","md","csv"): return data.decode("utf-8",errors="replace")
    if ext == "pdf": return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    if ext == "docx": return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    raise HTTPException(415,"Supported files: PDF, DOCX, TXT, MD, CSV")

app=FastAPI(title="Interview Lens",docs_url=None,redoc_url=None)

@app.get("/health")
def health(): return {"ok":True}

@app.get("/",response_class=HTMLResponse)
def home(): return HTMLResponse(MANAGER_HTML)

@app.get("/api/state")
def state(x_app_token: str|None=Header(None)):
    auth(x_app_token)
    with connect() as db: return snapshot(db)

@app.post("/api/profiles")
def create_profile(name: str=Form(...), job_description: str=Form(""), x_app_token: str|None=Header(None)):
    auth(x_app_token); pid=str(uuid.uuid4())
    with connect() as db:
        db.execute("UPDATE profiles SET active=0"); db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)",(pid,name.strip(),job_description.strip(),1,time.time())); db.commit()
    return {"id":pid}

@app.post("/api/profiles/{pid}/activate")
def activate(pid: str,x_app_token: str|None=Header(None)):
    auth(x_app_token)
    with connect() as db:
        if not db.execute("SELECT 1 FROM profiles WHERE id=?",(pid,)).fetchone(): raise HTTPException(404,"Profile not found")
        db.execute("UPDATE profiles SET active=(id=?)",(pid,)); db.commit()
    return {"ok":True}

@app.post("/api/profiles/{pid}/documents")
async def upload(pid: str,kind: str=Form(...),file: UploadFile=File(...),x_app_token: str|None=Header(None)):
    auth(x_app_token); data=await file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD: raise HTTPException(413,"File exceeds 8 MB")
    text=extract(file.filename or "upload.txt",data).strip()
    if not text: raise HTTPException(422,"No readable text found")
    did=str(uuid.uuid4())
    with connect() as db:
        if not db.execute("SELECT 1 FROM profiles WHERE id=?",(pid,)).fetchone(): raise HTTPException(404,"Profile not found")
        db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)",(did,pid,file.filename,kind,text,time.time())); db.commit()
    return {"id":did,"characters":len(text)}

@app.delete("/api/documents/{did}")
def delete_document(did: str,x_app_token: str|None=Header(None)):
    auth(x_app_token)
    with connect() as db: db.execute("DELETE FROM documents WHERE id=?",(did,)); db.commit()
    return {"ok":True}

@app.websocket("/ws/glasses")
async def glasses(ws: WebSocket):
    if ws.query_params.get("token") != os.getenv("APP_TOKEN") or not os.getenv("APP_TOKEN"): await ws.close(code=1008); return
    await ws.accept()
    with connect() as db: p=active_profile(db); profile_id=p["id"]; profile_name=p["name"]
    await ws.send_json({"type":"ready","profile":profile_name})
    transcription=await openai_transcription_session(); started=time.perf_counter(); task=None; sent={}; acks=[]; rate_state=None
    async def receive_stt():
        nonlocal started, task
        async for raw in transcription:
            msg=json.loads(raw)
            if msg.get("type")=="input_audio_buffer.speech_started": started=time.perf_counter(); continue
            if msg.get("type")!="conversation.item.input_audio_transcription.completed": continue
            utterance=msg.get("transcript","").strip()
            if not utterance: continue
            if not is_question(utterance): await ws.send_json({"type":"state","state":"listening"}); started=time.perf_counter(); continue
            stt_ms=(time.perf_counter()-started)*1000
            if task and not task.done(): task.cancel()
            task=__import__("asyncio").create_task(generate(utterance,stt_ms)); started=time.perf_counter()
    async def generate(question: str, stt_ms: float):
        t0=time.perf_counter(); await ws.send_json({"type":"state","state":"question detected","transcript":question})
        with connect() as db: evidence=search(chunks_for(db,profile_id),question)
        retrieval_ms=(time.perf_counter()-t0)*1000; grounded="\n\n".join(f"[{c.source}] {c.text}" for c in evidence) or "No matching candidate evidence was uploaded."
        full=""; first=None; answer_id=str(uuid.uuid4()); seq=0
        async for delta in answer_stream(question,grounded):
            if first is None: first=time.perf_counter(); model_ms=(first-t0)*1000
            full+=delta; seq+=1; sent[(answer_id,seq)]=time.perf_counter(); await ws.send_json({"type":"answer.delta","text":delta,"first":len(full)==len(delta),"answer_id":answer_id,"seq":seq})
        await __import__("asyncio").sleep(.08)
        total=(time.perf_counter()-t0)*1000; mine=[a for a in acks if a[0]==answer_id]
        transport_ms=round(sum(a[2] for a in mine)/len(mine)/2) if mine else None
        display_ms=round(sum(a[3] for a in mine)/len(mine)) if mine else None
        metrics={"stt_ms":round(stt_ms),"retrieval_ms":round(retrieval_ms),"model_first_token_ms":round((first-t0)*1000 if first else total),"transport_ms":transport_ms,"display_estimate_ms":display_ms,"total_ms":round(total)}
        await ws.send_json({"type":"answer.done","text":full,"metrics":metrics})
        with connect() as db:
            db.execute("INSERT INTO metrics(profile_id,created_at,question,stt_ms,retrieval_ms,model_first_token_ms,transport_ms,display_estimate_ms,total_ms) VALUES(?,?,?,?,?,?,?,?,?)",(profile_id,time.time(),question,*metrics.values())); db.commit()
    stt_task=__import__("asyncio").create_task(receive_stt())
    try:
        while True:
            event=await ws.receive()
            if event.get("bytes"):
                pcm24,rate_state=audioop.ratecv(event["bytes"],2,1,16000,24000,rate_state)
                await transcription.send(json.dumps({"type":"input_audio_buffer.append","audio":base64.b64encode(pcm24).decode("ascii")}))
            elif event.get("text"):
                msg=json.loads(event["text"])
                if msg.get("type")=="display.ack":
                    key=(msg.get("answer_id"),msg.get("seq")); then=sent.pop(key,None)
                    if then: acks.append((key[0],key[1],(time.perf_counter()-then)*1000,float(msg.get("display_call_ms",0))))
    except (WebSocketDisconnect,RuntimeError): pass
    finally:
        stt_task.cancel(); await transcription.close()

MANAGER_HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Interview Lens Manager</title><style>body{font:16px system-ui;background:#f1f5f1;color:#18251b;margin:0}.wrap{max-width:760px;margin:auto;padding:20px}.card{background:#fff;border:1px solid #dce5dc;border-radius:16px;padding:18px;margin:14px 0}input,textarea,select,button{font:inherit;width:100%;padding:11px;margin:6px 0;box-sizing:border-box;border:1px solid #bdc9bd;border-radius:9px}button{background:#19492b;color:#fff;font-weight:700}.row{display:flex;gap:8px}.muted{color:#68746a;font-size:14px}.pill{display:inline-block;background:#e5f2e8;padding:4px 8px;border-radius:9px;margin:3px}pre{white-space:pre-wrap}</style></head><body><div class="wrap"><h1>Interview Lens</h1><p class="muted">Private profile and latency manager</p><div class="card"><label>Access token</label><input id="token" type="password"><button onclick="load()">Unlock</button><div id="msg"></div></div><div id="app"></div></div><script>
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); let state;
async function api(path,opts={}){opts.headers={...(opts.headers||{}),'X-App-Token':$('#token').value};const r=await fetch(path,opts);if(!r.ok)throw Error(await r.text());return r.json()}
async function load(){try{state=await api('/api/state');render();$('#msg').textContent='Unlocked'}catch(e){$('#msg').textContent=e.message}}
function render(){const active=state.profiles.find(p=>p.active)||state.profiles[0];$('#app').innerHTML=`<div class="card"><h2>Interview profiles</h2>${state.profiles.map(p=>`<button onclick="activate('${p.id}')">${p.active?'✓ ':''}${esc(p.name)}</button>`).join('')}<h3>New profile</h3><form onsubmit="createP(event)"><input name="name" placeholder="Role / company" required><textarea name="job_description" rows="7" placeholder="Paste the target job description"></textarea><button>Create & select</button></form></div><div class="card"><h2>Materials · ${esc(active.name)}</h2><form onsubmit="upload(event,'${active.id}')"><select name="kind"><option>resume</option><option>professional profile</option><option>roles and responsibilities</option><option>project details</option><option>other evidence</option></select><input name="file" type="file" accept=".pdf,.docx,.txt,.md,.csv" required><button>Upload</button></form>${active.documents.map(d=>`<div class="pill">${esc(d.kind)} · ${esc(d.name)} <a href="#" onclick="del('${d.id}')">×</a></div>`).join('')||'<p class="muted">Upload truthful candidate evidence before an interview.</p>'}</div><div class="card"><h2>Measured latency</h2><p class="muted">STT includes speech + endpointing. Transport is half the phone acknowledgement round trip; display is SDK update-call time, not a photons-on-lens guarantee.</p>${state.metrics.slice(0,10).map(m=>`<p><b>${m.total_ms} ms generation</b> · STT ${m.stt_ms} · retrieval ${m.retrieval_ms} · first token ${m.model_first_token_ms} · transport ${m.transport_ms??'n/a'} · display call ${m.display_estimate_ms??'n/a'}<br><span class="muted">${esc(m.question)}</span></p>`).join('')||'<p>No live measurements yet.</p>'}</div>`}
async function createP(e){e.preventDefault();await api('/api/profiles',{method:'POST',body:new FormData(e.target)});load()} async function activate(id){await api('/api/profiles/'+id+'/activate',{method:'POST'});load()} async function upload(e,id){e.preventDefault();await api('/api/profiles/'+id+'/documents',{method:'POST',body:new FormData(e.target)});load()} async function del(id){await api('/api/documents/'+id,{method:'DELETE'});load()}
</script></body></html>'''
