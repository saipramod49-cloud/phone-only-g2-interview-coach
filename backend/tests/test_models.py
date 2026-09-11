import asyncio
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import resolve_model, account_models, AnswerModelError
from app import providers


def test_model_effort_validation_and_custom_snapshot_ids(monkeypatch):
    monkeypatch.setenv('OPENAI_MODEL','gpt-6-astra')
    assert resolve_model()==('gpt-6-astra','low')
    assert resolve_model('gpt-5.6-sol','none')==('gpt-5.6-sol','none')
    assert resolve_model('gpt-5.6-terra','high')==('gpt-5.6-terra','high')
    assert resolve_model('gpt-4.1')==('gpt-4.1',None)
    assert resolve_model('ft:gpt-4.1:my-org:coach:abc','default')==('ft:gpt-4.1:my-org:coach:abc',None)
    assert resolve_model('future-text-model-2030','default')==('future-text-model-2030',None)
    for model,effort in [('gpt-6-astra','none'),('gpt-4.1','low'),('gpt-image-1','default'),('gpt-realtime','auto'),('https://bad.example','auto'),('gpt-5-mini','invented'),('gpt-5-mini',[])]:
        with pytest.raises(ValueError):resolve_model(model,effort)


def test_account_list_requires_auth_and_preserves_all_valid_ids(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token');monkeypatch.setenv('OPENAI_API_KEY','private-api-key')
    requests=[]
    class Response:
        status_code=200
        def json(self):return {'data':[{'id':m} for m in ['gpt-6-astra','gpt-5.6-sol','ft:gpt-4.1:org:test:id','unknown-new-model','gpt-image-1','gpt-6-astra','<script>bad</script>']]}
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,url,**kwargs):requests.append((url,kwargs));return Response()
    with patch('app.models.httpx.AsyncClient',Client),TestClient(app) as client:
        assert client.get('/api/models').status_code==401
        assert not requests
        response=client.get('/api/models',headers={'X-App-Token':'test-token'})
    assert response.status_code==200
    rows={row['id']:row for row in response.json()['models']}
    assert len(rows)==5 and rows['unknown-new-model']['selectable']
    assert not rows['gpt-image-1']['selectable']
    assert 'private-api-key' not in response.text
    assert requests[0][0]=='https://api.openai.com/v1/models'


def test_account_list_error_does_not_expose_provider_body(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','private-api-key')
    class Response:
        status_code=403
        def json(self):raise AssertionError('Do not read provider body on this error path')
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,*args,**kwargs):return Response()
    with patch('app.models.httpx.AsyncClient',Client),pytest.raises(AnswerModelError,match='HTTP 403'):
        asyncio.run(account_models())


def test_reasoning_and_custom_models_build_compatible_payloads(monkeypatch):
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
        for model,effort in [('gpt-5.6-sol','none'),('gpt-5.6-luna','high'),('gpt-4.1','auto'),('ft:gpt-4.1:org:test:id','default')]:
            assert [s async for s in providers.answer_stream('Why?','','','english',model,effort)]==['Answer']
    with patch('app.providers.httpx.AsyncClient',Client):asyncio.run(run())
    assert payloads[0]['reasoning']=={'effort':'none'}
    assert payloads[1]['reasoning']=={'effort':'high'}
    assert 'reasoning' not in payloads[2] and 'reasoning' not in payloads[3]
    assert payloads[3]['model']=='ft:gpt-4.1:org:test:id'
    assert all(p['stream'] for p in payloads)


def test_retry_uses_new_model_same_question_and_reports_timing(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token')
    calls=[]
    class Session:
        def __init__(self):self.queue=asyncio.Queue()
        def __aiter__(self):return self
        async def __anext__(self):return await self.queue.get()
        async def close(self):pass
        async def send(self,raw):await self.queue.put(json.dumps({'type':'conversation.item.input_audio_transcription.completed','item_id':'1','transcript':'Explain CDC retry ordering?'}))
    async def connect():return Session()
    async def answer(question,evidence,context,language,model,effort,coach_instructions=""):
        calls.append((question,context,model,effort));yield 'Preserve sequence ordering.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type':'auth','token':'test-token'});assert 'all_models' in ws.receive_json()['features']
            ws.send_json({'type':'listen','continuous':True,'model':'gpt-5.6-sol','reasoning_effort':'low'})
            assert ws.receive_json()['active']
            ws.send_bytes(b'\x01\x01'*160)
            assert ws.receive_json()['type']=='transcript.partial'
            assert ws.receive_json()['type']=='transcript.final'
            first=ws.receive_json();assert first['model']=='gpt-5.6-sol'
            delta=ws.receive_json();assert delta['first_text_ms']>=0
            done=ws.receive_json();assert done['total_ms']>=done['first_text_ms']
            ws.send_json({'type':'settings','model':'gpt-image-1'})
            assert ws.receive_json()['type']=='state'
            ws.send_json({'type':'retry','model':'custom-text-snapshot','reasoning_effort':'default'})
            second=ws.receive_json();assert second['type']=='answer.start' and second['model']=='custom-text-snapshot'
            assert second['reasoning']=='API default'
            assert ws.receive_json()['type']=='answer.delta';assert ws.receive_json()['type']=='answer.done'
            ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'
    assert len(calls)==2 and calls[0][0]==calls[1][0]
    assert calls[0][1]==calls[1][1] # Retry removes the previous answer from history.
    assert calls[1][2:]==('custom-text-snapshot','default')
