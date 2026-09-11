import asyncio
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app import providers

class FakeSTT:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = False
        self.audio = []
    def __aiter__(self): return self
    async def __anext__(self): return await self.queue.get()
    async def send(self, raw):
        event=json.loads(raw)
        if event['type']=='input_audio_buffer.append':
            self.audio.append(event['audio'])
            await self.queue.put(json.dumps({'type':'conversation.item.input_audio_transcription.delta','delta':'Why'}))
            await self.queue.put(json.dumps({'type':'conversation.item.input_audio_transcription.completed','transcript':'Why?'}))
    async def close(self): self.closed=True

def test_live_audio_stream_context_and_auth(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token')
    sessions=[];contexts=[]
    async def connect():
        session=FakeSTT();sessions.append(session);return session
    async def answer(question,evidence,context):
        contexts.append(context)
        yield 'Use '
        yield 'CDC.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.answer_stream',answer):
        with TestClient(app) as client:
            with client.websocket_connect('/ws/live') as ws:
                ws.send_json({'type':'auth','token':'test-token'})
                assert ws.receive_json()['type']=='ready'
                for turn in range(2):
                    ws.send_json({'type':'listen'})
                    assert ws.receive_json()=={'type':'capture','active':True}
                    ws.send_bytes(b'\x00\x01'*1600)
                    assert ws.receive_json()['type']=='transcript.partial'
                    assert ws.receive_json()=={'type':'capture','active':False}
                    assert ws.receive_json()['type']=='transcript.final'
                    start=ws.receive_json();assert start['type']=='answer.start'
                    assert ws.receive_json()['text']=='Use '
                    assert ws.receive_json()['text']=='CDC.'
                    assert ws.receive_json()['text']=='Use CDC.'
                    # Audio after endpointing must not start another answer.
                    ws.send_bytes(b'\x00\x01'*1600)
                    ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'
                assert contexts[0]==''
                assert 'user: Why?' in contexts[1] and 'assistant: Use CDC.' in contexts[1]
                assert all(len(s.audio)==1 for s in sessions)
            with client.websocket_connect('/ws/live') as ws:
                ws.send_json({'type':'auth','token':'wrong'})
                event=ws.receive();assert event['type']=='websocket.close' and event['code']==1008
    assert all(s.closed for s in sessions)

def test_transcription_start_failure_is_visible(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token')
    async def fail(): raise RuntimeError('upstream')
    with patch('app.live.openai_transcription_session',fail),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type':'auth','token':'test-token'});ws.receive_json()
            ws.send_json({'type':'listen'})
            assert ws.receive_json()['type']=='error'
            ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'

def test_provider_streams_before_upstream_finishes(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    completed=[]
    class Response:
        status_code=200
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def aiter_lines(self):
            yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'First '})
            completed.append(True)
            yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'second.'})
            yield 'data: '+json.dumps({'type':'response.completed'})
    class Client(Response):
        def __init__(self,**kwargs): pass
        def stream(self,*args,**kwargs): return Response()
    async def run():
        stream=providers.answer_stream('Question','Evidence')
        assert await anext(stream)=='First '
        assert not completed
        assert await anext(stream)=='second.'
        await stream.aclose()
    with patch('app.providers.httpx.AsyncClient',Client): asyncio.run(run())
