from __future__ import annotations
import json, os, sqlite3, time, uuid
from pathlib import Path
from .retrieval import Chunk, chunk_text

ROOT = Path(os.getenv("DATA_DIR", Path(__file__).parents[1] / "data"))
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "interview_lens.sqlite3"

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL,job_description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,created_at REAL NOT NULL,FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE);
      CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY AUTOINCREMENT,profile_id TEXT,created_at REAL,question TEXT,stt_ms REAL,retrieval_ms REAL,model_first_token_ms REAL,transport_ms REAL,display_estimate_ms REAL,total_ms REAL);
    """)
    if not db.execute("SELECT 1 FROM profiles LIMIT 1").fetchone():
        db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)", (str(uuid.uuid4()),"My interview","",1,time.time()))
    db.commit(); return db

def active_profile(db):
    return db.execute("SELECT * FROM profiles ORDER BY active DESC,created_at DESC LIMIT 1").fetchone()

def core_profile_for(db, profile_id: str) -> str:
    row=db.execute("SELECT text FROM documents WHERE profile_id=? AND kind='core_profile' ORDER BY created_at DESC LIMIT 1",(profile_id,)).fetchone()
    return row[0][:4000] if row else ""

def chunks_for(db, profile_id: str, include_core: bool = True) -> list[Chunk]:
    chunks=[]
    p=db.execute("SELECT job_description FROM profiles WHERE id=?",(profile_id,)).fetchone()
    if p and p[0]: chunks += chunk_text("Target job description", p[0])
    for d in db.execute("SELECT name,text,kind FROM documents WHERE profile_id=?",(profile_id,)):
        if include_core or d["kind"] != "core_profile":
            chunks += chunk_text(d["name"], d["text"])
    return chunks

def snapshot(db):
    profiles=[]
    for p in db.execute("SELECT * FROM profiles ORDER BY active DESC,created_at DESC"):
        item=dict(p); item["documents"]=[dict(d) | {"text": None} for d in db.execute("SELECT id,name,kind,created_at FROM documents WHERE profile_id=?",(p["id"],))]; profiles.append(item)
    metrics=[dict(m) for m in db.execute("SELECT * FROM metrics ORDER BY id DESC LIMIT 25")]
    return {"profiles":profiles,"metrics":metrics}
