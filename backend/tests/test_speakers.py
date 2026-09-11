import asyncio
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.speakers import SpeakerTimeline
from app import providers


def test_timeline_abstains_on_mixed_or_missing_audio():
    t=SpeakerTimeline();t.append(32000,'interviewer');t.append(32000,'candidate')
    assert t.role(0,1000)=='interviewer'
    assert t.role(1000,2000)=='candidate'
    assert t.role(500,1500)=='unknown'
    assert t.role(None,2000)=='unknown'
    assert t.role(2000,3000)=='unknown'


def test_candidate_speech_follows_without_generating_an_answer(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token')
    questions=[]
    chosen=[]
    class Session:
        def __init__(self):self.queue=asyncio.Queue();self.count=0
        def __aiter__(self):return self
        async def __anext__(self):return await self.queue.get()
        async def close(self):pass
        async def send(self,raw):
            self.count+=1;item=str(self.count)
            transcript='Explain CDC retries' if self.count==1 else 'Preserve the delete tombstone'
            for event in [
                {'type':'input_audio_buffer.speech_started','item_id':item,'audio_start_ms':(self.count-1)*1000},
                {'type':'input_audio_buffer.speech_stopped','item_id':item,'audio_end_ms':self.count*1000},
                {'type':'conversation.item.input_audio_transcription.completed','item_id':item,'transcript':transcript},
            ]:await self.queue.put(json.dumps(event))
    async def connect():return Session()
    async def answer(question,evidence,context,language='english',model=None, reasoning_effort="auto"):questions.append(question);chosen.append((language,model));yield 'Preserve the delete tombstone.'
    async def align(spoken,answer):return 'Preserve the delete tombstone'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.answer_stream',answer),patch('app.live.align_candidate_speech',align),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type':'auth','token':'test-token'});ws.receive_json()
            ws.send_json({'type':'listen','continuous':True,'speaker_gate':True,'voice_follow':True})
            assert ws.receive_json()['active']
            ws.send_json({'type':'settings','model':'gpt-6-astra','output_language':'telugu_latin'})
            assert ws.receive_json()['type']=='state'
            ws.send_json({'type':'speaker','role':'interviewer'});ws.send_bytes(b'\x01\x01'*16000)
            assert ws.receive_json()['type']=='transcript.partial'
            assert ws.receive_json()['type']=='transcript.final'
            start=ws.receive_json();assert start['type']=='answer.start'
            assert ws.receive_json()['type']=='answer.delta';assert ws.receive_json()['type']=='answer.done'
            ws.send_json({'type':'speaker','role':'candidate'});ws.send_bytes(b'\x01\x01'*16000)
            assert ws.receive_json()['type']=='candidate.transcript'
            follow=ws.receive_json();assert follow['type']=='follow' and follow['answer_id']==start['answer_id']
            ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'
            assert questions==['Explain CDC retries']
            assert chosen==[('telugu_latin','gpt-6-astra')]


def test_astra_request_uses_documented_low_reasoning(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    payloads=[]
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
        return [s async for s in providers.answer_stream('Why?','','','telugu_latin','gpt-6-astra')]
    with patch('app.providers.httpx.AsyncClient',Client):assert asyncio.run(run())==['Answer']
    assert payloads[0]['model']=='gpt-6-astra'
    assert payloads[0]['reasoning']=={'effort':'low'}
    assert 'Romanized Telugu' in payloads[0]['input'][0]['content']


def test_alignment_rejects_invented_ambiguous_and_incomplete_results(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    result={}
    class Response:
        def raise_for_status(self):pass
        def json(self):return result
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):return Response()
    async def check():
        for quote,answer,status,expected in [
            ('retain the delete tombstone','We retain the delete tombstone.','completed','retain the delete tombstone'),
            ('invent an unrelated phrase','We retain the delete tombstone.','completed',None),
            ('retain the delete tombstone','retain the delete tombstone; retain the delete tombstone','completed',None),
            ('retain the delete tombstone','We retain the delete tombstone.','incomplete',None),
        ]:
            result.clear();result.update(status=status,output=[{'content':[{'type':'output_text','text':json.dumps({'quote':quote})}]}])
            assert await providers.align_candidate_speech('spoken words go here',answer)==expected
    with patch('app.providers.httpx.AsyncClient',Client):asyncio.run(check())


def test_failed_transcription_setup_closes_upstream_socket(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    class Session:
        closed=False
        async def send(self,data):raise RuntimeError('simulated send failure')
        async def close(self):self.closed=True
    session=Session()
    async def connect(*args,**kwargs):return session
    async def check():
        try:await providers.openai_transcription_session()
        except RuntimeError:pass
        else:assert False,'expected setup failure'
        assert session.closed
    with patch('app.providers.websockets.connect',connect):asyncio.run(check())
