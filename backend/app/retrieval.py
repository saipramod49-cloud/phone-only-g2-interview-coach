from __future__ import annotations
import math, re
from collections import Counter
from dataclasses import dataclass

TOKEN = re.compile(r"[a-zA-Z0-9+#.-]{2,}")

@dataclass(frozen=True)
class Chunk:
    source: str
    text: str

def chunk_text(source: str, text: str, size: int = 900, overlap: int = 120) -> list[Chunk]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(". ", start + size // 2, end)
            if cut > start: end = cut + 1
        out.append(Chunk(source, text[start:end]))
        if end == len(text): break
        start = max(start + 1, end - overlap)
    return out

def _terms(text: str) -> Counter[str]:
    return Counter(t.lower() for t in TOKEN.findall(text))

def search(chunks: list[Chunk], query: str, limit: int = 5) -> list[Chunk]:
    if not chunks: return []
    q = _terms(query)
    docs = [_terms(c.text) for c in chunks]
    df = Counter(term for d in docs for term in d)
    n = len(docs)
    def score(d: Counter[str]) -> float:
        total = sum(d.values()) or 1
        return sum((1 + math.log(d[t])) * math.log((n + 1) / (df[t] + 0.5)) * (1 + math.log(qt)) / total for t, qt in q.items() if d[t])
    ranked = sorted(zip(chunks, docs), key=lambda x: score(x[1]), reverse=True)
    return [c for c, d in ranked[:limit] if score(d) > 0]
