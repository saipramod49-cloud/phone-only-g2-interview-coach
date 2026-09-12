import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cloud'))
import ring_agent

def stream_bytes(parts,finish='stop'):
    events=[{'choices':[{'delta':{'content':text},'finish_reason':None}]} for text in parts]
    if finish:events.append({'choices':[{'delta':{},'finish_reason':finish}]})
    return io.BytesIO(b''.join(b'data: '+json.dumps(x).encode()+b'\n\n' for x in events)+b'data: [DONE]\n')
class StreamTests(unittest.TestCase):
    def test_every_word_streamed_without_native_page_limit(self):
        parts=['This is a complete explanation. ']*50
        with patch.object(ring_agent.urllib.request,'urlopen',return_value=stream_bytes(parts)):
            agent=ring_agent.RingConversation();items=list(agent.stream('Explain the project','gpt-5.6-sol','fake'))
        answer=''.join(x['text'] for x in items if x['type']=='delta')
        self.assertEqual(answer,''.join(parts));self.assertGreater(len(answer),360)
        self.assertEqual(items[-1]['type'],'done');self.assertEqual(agent.history[-1]['content'],answer.strip())
    def test_first_delta_arrives_before_response_is_complete(self):
        with patch.object(ring_agent.urllib.request,'urlopen',return_value=stream_bytes(['First sentence. ','Second sentence.'])):
            agent=ring_agent.RingConversation();stream=agent.stream('question','gpt-5.6-sol','fake')
            self.assertEqual(next(stream),{'type':'delta','text':'First sentence. '});self.assertEqual(len(agent.history),0)
            self.assertEqual(next(stream),{'type':'delta','text':'Second sentence.'});list(stream)
            self.assertEqual(len(agent.history),2)
    def test_followup_receives_previous_complete_answer(self):
        agent=ring_agent.RingConversation()
        with patch.object(ring_agent.urllib.request,'urlopen',return_value=stream_bytes(['I use TIDAL for the QFC workload.'])):
            list(agent.stream('Which scheduler?','gpt-5.6-sol','fake'))
        with patch.object(ring_agent.urllib.request,'urlopen',return_value=stream_bytes(['It handles dependencies.'])) as call:
            list(agent.stream('Why that one?','gpt-5.6-sol','fake'))
            messages=json.loads(call.call_args.args[0].data)['messages']
            self.assertEqual(messages[-2]['content'],'I use TIDAL for the QFC workload.')
    def test_interrupted_answer_is_not_added_to_history(self):
        with patch.object(ring_agent.urllib.request,'urlopen',return_value=stream_bytes(['Partial'],finish=None)):
            agent=ring_agent.RingConversation()
            with self.assertRaises(RuntimeError):list(agent.stream('q','gpt-5.6-sol','fake'))
            self.assertEqual(len(agent.history),0)
    def test_style_and_evidence_are_separate_from_native_bullet_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            profile=Path(folder)/'profile.md';profile.write_text('Verified note: QFC uses Snowflake and TIDAL.')
            with patch.object(ring_agent.bridge,'EXPERIENCE',profile):
                prompt=ring_agent.prompt('natural')
                self.assertIn(profile.read_text(),prompt);self.assertIn('60–100',prompt)
                self.assertNotIn('Reply with one to three short bullet points',prompt)
if __name__=='__main__':unittest.main()
