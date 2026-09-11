import asyncio
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app import storage, providers
from app.retrieval import Chunk, search_live

class Stream:
    def __init__(self,texts):self.queue=asyncio.Queue();self.texts=texts;self.count=0;self.closed=False
    def __aiter__(self):return self
    async def __anext__(self):return await self.queue.get()
    async def close(self):self.closed=True
    async def send(self,raw):
        self.count+=1;item=str(self.count)
        for e in [{'type':'input_audio_buffer.speech_started','item_id':item},
                  {'type':'input_audio_buffer.speech_stopped','item_id':item},
                  {'type':'input_audio_buffer.committed','item_id':item,'previous_item_id':str(self.count-1) if self.count>1 else None},
                  {'type':'conversation.item.input_audio_transcription.completed','item_id':item,'transcript':self.texts[self.count-1]}]:await self.queue.put(json.dumps(e))

def until(ws,kind,phase=None):
    seen=[]
    for _ in range(40):
        m=ws.receive_json();seen.append(m)
        if m['type']==kind and (phase is None or m.get('phase')==phase):return m,seen
    raise AssertionError(seen)

def start(ws,**extra):
    ws.send_json({'type':'auth','token':'test-token'});assert ws.receive_json()['build']=='0.2.8'
    ws.send_json({'type':'listen','continuous':True,'turn_mode':'semantic','quiet_seconds':0.5,'flow_events':True,**extra})
    assert ws.receive_json()=={'type':'capture','active':True}


def test_story_survives_pauses_and_original_question_reaches_answer(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token')
    story='Our source crashed after the sink committed. We still have six months of history to rebuild.'
    request='Design recovery while live updates continue, including deletes, ordering and validation.'
    session=Stream([story,request]);calls=[];judged=[]
    async def connect():return session
    async def judge(text,*args):judged.append(text);return {'decision':'question' if 'Design recovery' in text else 'wait','retrieval_query':'CDC recovery delete ordering'}
    async def answer(question,*args):calls.append(question);yield 'A complete scenario answer.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.assess_turn',judge),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws);ws.send_bytes(b'\x01\x01'*160)
            until(ws,'flow','waiting');assert calls==[] and not session.closed
            ws.send_bytes(b'\x01\x01'*160);m,events=until(ws,'answer.done')
            assert calls==[story+' '+request]
            assert any(e.get('text')==story+' '+request for e in events if e['type']=='transcript.partial')
            assert not session.closed


def test_new_speech_cancels_pending_turn_decision(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token');session=Stream(['Explain retries.','Also preserve the delete tombstones.']);calls=[]
    async def connect():return session
    async def judge(text,*args):await asyncio.sleep(.15);return {'decision':'question','retrieval_query':''}
    async def answer(question,*args):calls.append(question);yield 'Both requirements.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.assess_turn',judge),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws);ws.send_bytes(b'\x01\x01'*160);until(ws,'flow','checking')
            ws.send_bytes(b'\x01\x01'*160);until(ws,'answer.done')
            assert calls==['Explain retries. Also preserve the delete tombstones.']


def test_turn_check_failure_retains_question_and_manual_finish_keeps_listening(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token');session=Stream(['A long story and its complete request.']);calls=[]
    async def connect():return session
    async def judge(*args):raise TimeoutError()
    async def answer(question,*args):calls.append(question);yield 'Answer.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.assess_turn',judge),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws);ws.send_bytes(b'\x01\x01'*160);until(ws,'state');assert not calls
            ws.send_json({'type':'finish'});until(ws,'answer.done')
            assert calls==['A long story and its complete request.'] and not session.closed


def test_selected_profile_overrides_global_default_and_unrelated_notes_are_excluded(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_TOKEN','test-token');monkeypatch.setattr(storage,'DB',tmp_path/'profile.sqlite3')
    with storage.connect() as db:
        db.execute('INSERT INTO profiles VALUES(?,?,?,?,?)',('profile-b','Second profile','',0,2))
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',('core-b','profile-b','core','core_profile','Candidate B worked on a warehouse.',2))
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',('note-b','profile-b','unrelated','notes','Gardening roses needs sunlight.',2));db.commit()
    session=Stream(['Explain BigQuery partition pruning.']);calls=[]
    async def connect():return session
    async def judge(*args):return {'decision':'question','retrieval_query':'BigQuery partition pruning'}
    async def answer(question,evidence,*args):calls.append(evidence);yield 'Partition filtering.'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.assess_turn',judge),patch('app.live.answer_stream',answer),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws,profile_id='profile-b');ws.send_bytes(b'\x01\x01'*160);until(ws,'answer.done')
            assert 'Candidate B' in calls[0] and 'Gardening' not in calls[0]
            ws.send_json({'type':'retry','profile_id':'profile-b','grounding_mode':'general'});until(ws,'answer.done')
            assert calls[1]==''


def test_unknown_speaker_readback_can_follow_without_generating_a_new_answer(monkeypatch):
    monkeypatch.setenv('APP_TOKEN','test-token');session=Stream(['Explain retry recovery.','I preserve the delete tombstone and then replay safely.']);calls=[]
    async def connect():return session
    async def judge(text,*args):return {'decision':'candidate' if text.startswith('I preserve') else 'question','retrieval_query':''}
    async def answer(question,*args):calls.append(question);yield 'I preserve the delete tombstone and then replay safely.'
    async def align(*args):return 'then replay safely'
    with patch('app.live.openai_transcription_session',connect),patch('app.live.assess_turn',judge),patch('app.live.answer_stream',answer),patch('app.live.align_candidate_speech',align),TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws,voice_follow=True);ws.send_bytes(b'\x01\x01'*160);until(ws,'answer.done')
            ws.send_bytes(b'\x01\x01'*160);follow,events=until(ws,'follow')
            assert len(calls)==1 and follow['quote']=='then replay safely'
            assert any(e.get('estimated') for e in events if e['type']=='flow')


def test_retrieval_never_falls_back_to_arbitrary_notes():
    chunks=[Chunk('resume','My project processes customer orders in BigQuery.'),Chunk('unrelated','I water roses every evening.')]
    assert search_live(chunks,'Explain Kubernetes probes.')==[]
    assert [c.source for c in search_live(chunks,'How do you optimize BigQuery?')]==['resume']
