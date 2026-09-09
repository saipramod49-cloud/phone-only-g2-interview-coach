from app.question import is_question
from app.retrieval import chunk_text, search

def test_question_gate_rejects_background_statement(): assert not is_question("the meeting starts in five minutes")
def test_question_gate_accepts_behavioral_question(): assert is_question("Tell me about a time when you resolved a conflict")
def test_retrieval_prefers_relevant_truth():
    chunks=chunk_text("resume","Led a Kubernetes migration that cut deploy time by 40%. Worked in retail sales.",45,0)
    assert "Kubernetes" in search(chunks,"Kubernetes migration example",1)[0].text
