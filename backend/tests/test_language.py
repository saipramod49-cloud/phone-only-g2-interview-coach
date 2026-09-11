import asyncio
import json
from unittest.mock import patch
from app import providers


def test_answer_language_is_explicit_and_question_is_preserved(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    payloads=[]
    class Response:
        status_code=200
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def aiter_lines(self):
            yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'Example answer'})
            yield 'data: '+json.dumps({'type':'response.completed'})
    class Client(Response):
        def __init__(self,**kwargs):pass
        def stream(self,*args,**kwargs):payloads.append(kwargs['json']);return Response()
    async def run():
        for language in ('english','telugu_latin'):
            result=[text async for text in providers.answer_stream('తెలుగులో CDC గురించి చెప్పండి','', '',language)]
            assert result==['Example answer']
    with patch('app.providers.httpx.AsyncClient',Client):asyncio.run(run())
    assert 'Answer in English' in payloads[0]['input'][0]['content']
    assert 'Romanized Telugu' in payloads[1]['input'][0]['content']
    assert all('తెలుగులో CDC గురించి చెప్పండి' in p['input'][1]['content'] for p in payloads)


def test_transcription_does_not_force_english(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    class Session:
        config=None
        async def send(self,data):self.config=json.loads(data)
        def __aiter__(self):return self
        async def __anext__(self):return json.dumps({'type':'session.updated'})
        async def close(self):pass
    session=Session()
    async def connect(*args,**kwargs):return session
    with patch('app.providers.websockets.connect',connect):
        assert asyncio.run(providers.openai_transcription_session()) is session
    assert 'language' not in session.config['session']['audio']['input']['transcription']
