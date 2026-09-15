"""Stream complete, grounded rehearsal answers; never use native voice pagination."""
from collections import deque
import json
import ssl
import time
import urllib.request
from pathlib import Path
import re
import bridge

STYLE = """Give one natural, technically accurate interview answer to the latest question. Use conversation context for follow-ups. Never output separate answer modes, page numbers, or repeat the question.

Adapt to the request:
- SQL/Python/PySpark code request: start with runnable fenced code in the requested dialect. Preserve indentation. Use stated names; if missing, use a small sensible schema and state the assumption after the code. Then give 2–3 short sentences on the mechanism and important correctness caveat. A follow-up such as "give me the SQL" means code for the previous question.
- Architecture/scenario: 3–4 short conversational paragraphs covering the relevant source, ingestion, storage, orchestration, processing, serving, and reliability. End with one bold arrow flow matching the explanation. Airflow orchestrates jobs; do not present it as a data transport hop.
- Troubleshooting: check scope first, trace the first failing layer, fix and safely reprocess, then validate. Use 3 short practical paragraphs and a flow only when useful.
- Comparison/definition: direct answer, mechanism, when to choose each, and one trade-off.
- Behavioral: situation, what I did, why, and result or lesson. Use supplied background when relevant without inventing experience or metrics.

Keep ordinary answers around 80–130 words and architecture/behavioral answers around 110–150 words. Code may run longer when completeness requires it. Lead directly, use plain English, split text for quick reading, and bold only a few useful terms. Avoid canned labels, greetings, "as per the records", résumé commentary, and filler.

Résumé notes guide personalization but never limit technical help. Treat every supplied project detail, metric, date, domain object, cause, sequence, and result as exact evidence: preserve it precisely, never embellish it, and never merge details from separate projects. For an unfamiliar stack give a realistic approach immediately using "I'd" or "A practical design is". Do not refuse because evidence is missing, and do not fabricate employment history. Keep Mizuho/QFC and Priceline separate. State only assumptions that affect correctness. Watch nulls and deterministic ties, deduplicate MERGE sources, make side effects idempotent, and do not treat a watermark as proof all records arrived.

Architecture tone example: "I'd land immutable raw events in **GCS**, orchestrate validation and transformation with Airflow, and publish reconciled data through **BigQuery**. **Website → ingestion → raw GCS → processing → BigQuery staging → curated tables**."
"""

def background_for(question):
    if not bridge.EXPERIENCE.exists(): return ''
    text = bridge.EXPERIENCE.read_text(encoding='utf-8').strip()
    sections = re.split(r'(?=^#{2,3} )', text, flags=re.MULTILINE)
    # The opening two paragraphs contain the role and core stack. Add only the
    # project section relevant to this question to reduce prompt-processing time.
    base = '\n\n'.join(sections[0].split('\n\n')[:3])
    q = question.lower()
    wanted = []
    rules = [
        (('priceline','website','booking','experiment'), ('priceline',)),
        (('mizuho','qfc','regulatory','reconciliation','snowflake','tidal'), ('mizuho',)),
        (('python','pyspark','pandas','numpy','dataproc'), ('python, pandas',)),
        (('aws','lti','kubernetes','eks'), ('lti: aws',)),
    ]
    for needles, headings in rules:
        if any(word in q for word in needles): wanted.extend(headings)
    relevant = [part for part in sections[1:] if any(name in part.split('\n',1)[0].lower() for name in wanted)]
    return '\n\n'.join([base, *relevant]).strip()

def prompt(style='natural', instructions='', question=''):
    background = background_for(question)
    request = ('\n<user_answer_request>\n'+instructions+'\n</user_answer_request>') if instructions else ''
    return STYLE + '\n<candidate_background>\n' + background + '\n</candidate_background>' + request

class RingConversation:
    def __init__(self):
        self.history = deque(maxlen=8)
        self.last_seen = time.monotonic()

    def stream(self, question, model, key, style='natural', instructions=''):
        if time.monotonic() - self.last_seen > 1800:
            self.history.clear()
        self.last_seen = time.monotonic()
        if question.lower().strip(' .!?') in ('new chat','reset conversation'):
            self.history.clear()
            yield {'type':'delta','text':'New conversation started.'}
            yield {'type':'done'}
            return
        effective_model = fast_model(question, model)
        payload = {'model':effective_model,'messages':[{'role':'system','content':prompt(style, instructions, question)}]+list(self.history)+[{'role':'user','content':question}],
                   'stream':True,'store':False,'reasoning_effort':'low',
                   'max_completion_tokens':1600}
        if effective_model in ('gpt-5.6-sol','gpt-6-astra'): payload['service_tier']='fast'
        request=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=json.dumps(payload).encode(),
                   headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        context=ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None)
        start=time.perf_counter();first=None;pieces=[];finish=None
        with urllib.request.urlopen(request,timeout=90,context=context) as response:
            for line in response:
                if time.perf_counter()-start>110: raise TimeoutError('Answer deadline exceeded')
                if not line.startswith(b'data:'):continue
                raw=line[5:].strip()
                if raw==b'[DONE]':break
                event=json.loads(raw)
                if event.get('error'):raise RuntimeError('Upstream stream error')
                for choice in event.get('choices',[]):
                    delta=choice.get('delta',{});text=delta.get('content') or delta.get('refusal')
                    if text:
                        if first is None:first=time.perf_counter()
                        pieces.append(text)
                        yield {'type':'delta','text':text}
                    finish=choice.get('finish_reason') or finish
        answer=''.join(pieces).strip()
        if not answer or not finish:raise RuntimeError('Incomplete upstream answer')
        if finish=='length':
            yield {'type':'error','text':'The answer reached its length limit. Ask a narrower follow-up.'}
            return
        self.history.extend([{'role':'user','content':question},{'role':'assistant','content':answer}])
        yield {'type':'done','model':effective_model,'timing':{'modelFirstTextMs':round((first-start)*1000),'modelTotalMs':round((time.perf_counter()-start)*1000)}}

def fast_model(question, default):
    if default != 'gpt-6-astra': return default
    q = question.lower()
    asks_to_write = any(term in q for term in ('write','give me','show me','provide','generate'))
    names_code = any(term in q for term in ('sql','query','python','pyspark','code','script'))
    code_request = (asks_to_write and names_code) or any(term in q for term in ('sql query','python code','pyspark code','show the code'))
    architecture_request = any(term in q for term in (
        'architecture','pipeline','data flow','data move','move data','end to end','end-to-end',
        'ingestion','orchestration','gcs','bigquery','data warehouse','data lake','design a system'))
    # These questions benefit more from low first-token latency than extended
    # deliberation. Keep Astra for behavioral and open-ended diagnosis.
    return 'gpt-5.6-sol' if code_request or architecture_request else default

conversation=RingConversation()
