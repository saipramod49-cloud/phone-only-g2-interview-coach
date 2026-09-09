from __future__ import annotations
import re

OPENERS = re.compile(r"^(what|why|how|when|where|who|which|tell me|walk me|describe|give me|have you|can you|could you|would you|do you|did you|are you|were you|explain)\b", re.I)

def is_question(text: str) -> bool:
    value = re.sub(r"\s+", " ", text).strip()
    if len(value.split()) < 4: return False
    if value.endswith("?") or OPENERS.search(value): return True
    return any(p in value.lower() for p in ("your experience with", "an example of", "a time when", "your approach to"))
