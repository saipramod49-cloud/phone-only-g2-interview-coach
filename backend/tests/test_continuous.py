import asyncio
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.turns import question_candidate


def test_question_gate_supports_followups_and_telugu():
    assert question_candidate('Why?')
    assert question_candidate('CDC ఎలా పని చేస్తుంది')
    assert not question_candidate("I'd first stage the CDC events.")
    assert not question_candidate('The meeting starts in five minutes.')


def test_continuous_two_questions_and_readback_share_one_capture(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token')
    questions=[];sessions=[]
    class Session:
        def __init__(self):self.queue=asyncio.Queue();self.count=0;self.closed=False
        def __aiter__(self):return self
        async def __anext__(self):return await self.queue.get()
        async def close(self):self.closed=True
        async def send(self,raw):
            self.count+=1;item=str(self.count)
            transcript=['How do you handle CDC retries?',"I'd first stage the CDC events.",'Why?'][self.count-1]
            for e in [
                {'type':'input_audio_buffer.speech_started','item_id':item},
                {'type':'input_audio_buffer.speech_stopped','item_id':item},
                {'type':'conversation.item.input_audio_transcription.completed','item_id':item,'transcript':transcript},
            ]:await self.queue.put(json.dumps(e))
    async def connect():
        session=Session();sessions.append(session);return session
    async def answer(question,evidence,context,output_language='english', model_override=None, reasoning_effort="auto"):
        questions.append(question);yield 'Use an idempotent MERGE.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type':'auth','token':'test-token'})
            assert 'continuous_questions' in ws.receive_json()['features']
            ws.send_json({'type':'listen','continuous':True})
            assert ws.receive_json()=={'type':'capture','active':True}
            for turn in range(3):
                ws.send_bytes(b'\x00\x01'*160)
                assert ws.receive_json()['type']=='transcript.partial'
                if turn==1:
                    assert ws.receive_json()['type']=='state'
                else:
                    assert ws.receive_json()['type']=='transcript.final'
                    assert ws.receive_json()['type']=='answer.start'
                    assert ws.receive_json()['type']=='answer.delta'
                    assert ws.receive_json()['type']=='answer.done'
            assert questions==['How do you handle CDC retries?','Why?']
            assert len(sessions)==1 and sessions[0].count==3
            assert not sessions[0].closed
            ws.send_json({'type':'pause'})
            assert ws.receive_json()=={'type':'capture','active':False}
            assert sessions[0].closed
