"""Conservative text-based question gate, not speaker recognition."""
import re
from .question import is_question


def question_candidate(text: str) -> bool:
    value=re.sub(r'\s+', ' ', text).strip()
    if not value:
        return False
    # Typical candidate read-back openings should not create another answer.
    if re.match(r"^(i['’]d|i would|i use|i first|i will|nenu|నేను)\b",value,re.I):
        return False
    if is_question(value) or value.endswith('?'):
        return True
    if re.fullmatch(r'(why|how|why not|what next|and then)[.!]?',value,re.I):
        return True
    return any(term in value for term in ('ఎలా','ఎందుకు','ఏమిటి','ఎప్పుడు','చెప్పండి','వివరించండి'))
