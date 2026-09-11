import asyncio
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app import providers,storage


def test_core_profile_is_bounded_replaced_and_separate_from_search(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_TOKEN','test-token');monkeypatch.setattr(storage,'DB',tmp_path/'core.sqlite3')
    headers={'X-App-Token':'test-token'}
    with TestClient(app) as client:
        pid=client.post('/api/profiles',headers=headers,data={'name':'TestCandidate'}).json()['id']
        def upload(text,kind='core_profile'):
            return client.post(f'/api/profiles/{pid}/documents',headers=headers,data={'kind':kind},files={'file':('profile.txt',text.encode(),'text/plain')})
        assert upload('Old role').status_code==200
        assert upload('TestCandidate supported ExampleCo pipelines.').status_code==200
        assert upload('x'*4001).status_code==422
        assert upload('Study example about CDC','notes').status_code==200
        with storage.connect() as db:
            assert storage.core_profile_for(db,pid)=='TestCandidate supported ExampleCo pipelines.'
            assert db.execute("SELECT COUNT(*) FROM documents WHERE kind='core_profile'").fetchone()[0]==1
            assert all('TestCandidate' not in c.text for c in storage.chunks_for(db,pid,include_core=False))
            assert any('TestCandidate' in c.text for c in storage.chunks_for(db,pid))


def test_preferences_and_core_reach_next_answer_and_clear_without_stopping_capture(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_TOKEN','test-token');monkeypatch.setattr(storage,'DB',tmp_path/'prefs.sqlite3')
    calls=[]
    with storage.connect() as db:
        pid=storage.active_profile(db)['id']
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',('core',pid,'core.txt','core_profile','TestCandidate worked on ExampleCo pipelines.',1.0));db.commit()
    class Session:
        def __init__(self):self.queue=asyncio.Queue();self.closed=False
        def __aiter__(self):return self
        async def __anext__(self):return await self.queue.get()
        async def close(self):self.closed=True
        async def send(self,raw):await self.queue.put(json.dumps({'type':'conversation.item.input_audio_transcription.completed','item_id':'1','transcript':'What is a watermark?'}))
    session=Session()
    async def connect():return session
    async def answer(question,evidence,context,language,model,effort,instructions):
        calls.append((evidence,instructions));yield 'A watermark estimates completeness.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type':'auth','token':'test-token'});assert 'coach_instructions' in ws.receive_json()['features']
            ws.send_json({'type':'coach.instructions','text':'Highlight three keywords.\nUse one short example.'});assert ws.receive_json()['active']
            ws.send_json({'type':'listen','continuous':True});assert ws.receive_json()['active']
            ws.send_bytes(b'\x01\x01'*160);assert ws.receive_json()['type']=='transcript.partial'
            assert ws.receive_json()['type']=='transcript.final'
            for kind in ['answer.start','answer.delta','answer.done']:assert ws.receive_json()['type']==kind
            ws.send_json({'type':'coach.instructions','text':'x'*4001});assert ws.receive_json()['type']=='state'
            ws.send_json({'type':'retry'})
            for kind in ['answer.start','answer.delta','answer.done']:assert ws.receive_json()['type']==kind
            ws.send_json({'type':'coach.instructions','text':''});assert not ws.receive_json()['active']
            ws.send_json({'type':'retry'})
            for kind in ['answer.start','answer.delta','answer.done']:assert ws.receive_json()['type']==kind
            assert not session.closed
    assert all('TestCandidate worked on ExampleCo' in evidence for evidence,_ in calls)
    assert calls[0][1]==calls[1][1]=='Highlight three keywords.\nUse one short example.'
    assert calls[2][1]==''


def test_provider_separates_preferences_from_evidence_and_allows_style_override(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only');payloads=[]
    class Response:
        status_code=200
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def aiter_lines(self):
            yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'Answer'})
            yield 'data: '+json.dumps({'type':'response.completed'})
    class Client(Response):
        def __init__(self,**kwargs):pass
        def stream(self,*args,**kwargs):payloads.append(kwargs['json']);return Response()
    async def run():
        return [s async for s in providers.answer_stream('Explain CDC','PRACTICE DESIGN only','','english','gpt-4.1','default','Do not highlight any keywords. Use 100 words.')]
    with patch('app.providers.httpx.AsyncClient',Client):assert asyncio.run(run())==['Answer']
    messages=payloads[0]['input']
    assert 'instead of the default style' in messages[0]['content']
    assert 'Never invent experience' in messages[0]['content']
    assert messages[1]['role']=='user' and 'Do not highlight' in messages[1]['content']
    assert 'PRACTICE DESIGN only' in messages[-1]['content']
    assert 'VERIFIED CANDIDATE EVIDENCE' not in messages[-1]['content']
