import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cloud'))
import ring_api
class Conversation:
    def ask(self,q,m,k):
        assert q=='What is a data warehouse?'
        return 'A store for analytical data.',{}
class RingTests(unittest.TestCase):
    def call(self,path='/api/ask',auth='Bearer test',body=b'\0'*6400,method='POST',extra=None):
        status=[]
        env={'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_AUTHORIZATION':auth,'CONTENT_TYPE':'application/octet-stream','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body)}
        env.update(extra or {})
        response=ring_api.handle(env,lambda s,h:status.append(s),{'bridge_token':'test','api_key':'fake'},Conversation(),'gpt-5.6-sol')
        return status,b''.join(response) if response is not None else None
    def test_bad_token(self):
        with patch.object(ring_api,'transcribe') as transcribe:
            status,_=self.call(auth='Bearer wrong');self.assertIn('401',status[0]);transcribe.assert_not_called()
    def test_invalid_audio(self):
        for body in [b'',b'1'*6401,b'1'*2880002]:
            status,_=self.call(body=body);self.assertIn('400',status[0])
    def test_submission_streams_full_ring_answer(self):
        with patch.object(ring_api,'transcribe',return_value='What is a data warehouse?'), patch.object(ring_api.ring_agent.conversation,'stream',return_value=iter([{'type':'delta','text':'A store for analytical data.'},{'type':'delta','text':' More detail.'},{'type':'done'}])):
            status,body=self.call();events=[json.loads(line) for line in body.splitlines()]
            self.assertEqual(status,['200 OK']);self.assertEqual([e['type'] for e in events],['status','transcript','delta','delta','done']);self.assertIn('analytical',events[2]['text'])
    def test_answer_format_and_request_reach_agent(self):
        with patch.object(ring_api,'transcribe',return_value='What is a data warehouse?'), patch.object(ring_api.ring_agent.conversation,'stream',return_value=iter([{'type':'done'}])) as stream:
            self.call(extra={'HTTP_X_ANSWER_STYLE':'technical','HTTP_X_ANSWER_INSTRUCTIONS':'Explain%20simply'})
            self.assertEqual(stream.call_args.args[-2:],('technical','Explain simply'))
    def test_failure_unlocks_next_question(self):
        with patch.object(ring_api,'transcribe',side_effect=RuntimeError('private details')):
            _,body=self.call();self.assertNotIn(b'private details',body);self.assertIn(b'error',body)
        self.assertFalse(ring_api._busy.locked())
    def test_existing_native_route_is_untouched(self):
        status,body=self.call(path='/v1/chat/completions');self.assertEqual(status,[]);self.assertIsNone(body)
    def test_busy_request_does_not_hold_a_second_lock(self):
        ring_api._busy.acquire()
        try:
            status,_=self.call();self.assertIn('429',status[0])
        finally:ring_api._busy.release()
    def test_closing_stream_releases_request_lock(self):
        env={'PATH_INFO':'/api/ask','REQUEST_METHOD':'POST','HTTP_AUTHORIZATION':'Bearer test','CONTENT_TYPE':'application/octet-stream','CONTENT_LENGTH':'6400','wsgi.input':io.BytesIO(b'\0'*6400)}
        stream=ring_api.handle(env,lambda s,h:None,{'bridge_token':'test','api_key':'fake'},Conversation(),'gpt-5.6-sol')
        self.assertFalse(ring_api._busy.locked())
        next(stream);self.assertTrue(ring_api._busy.locked())
        stream.close();self.assertFalse(ring_api._busy.locked())
    def test_wav_format(self):
        import wave
        raw=ring_api.wav_file(b'\0'*6400)
        with wave.open(io.BytesIO(raw)) as r:
            self.assertEqual(r.getframerate(),16000);self.assertEqual(r.getnchannels(),1);self.assertEqual(r.getsampwidth(),2);self.assertEqual(r.getnframes(),3200)
    def test_preflight(self):
        status,_=self.call(method='OPTIONS',auth='');self.assertIn('204',status[0])
    def test_static_traversal(self):
        status,_=self.call(path='/ring/../bridge.py',method='GET');self.assertIn('404',status[0])
if __name__=='__main__':unittest.main()
