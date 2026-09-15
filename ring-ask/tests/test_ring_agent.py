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
                prompt=ring_agent.prompt('natural',question='Tell me about QFC.')
                self.assertIn(profile.read_text(),prompt);self.assertIn('Give one natural',prompt);self.assertIn('start with runnable fenced code',prompt)
                self.assertNotIn('Reply with one to three short bullet points',prompt)
    def test_custom_request_and_format_are_added_to_prompt(self):
        prompt=ring_agent.prompt('technical','Explain the trade-off for a beginner.')
        self.assertIn('correctness',prompt)
        self.assertIn('<user_answer_request>\nExplain the trade-off for a beginner.',prompt)
    def test_relevant_profile_context_is_selected(self):
        profile='''# Candidate\n\nCore stack.\n\nCurrent role.\n\n### Priceline: platform\nPriceline detail.\n\n### Mizuho: reporting\nMizuho detail.'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'profile.md';path.write_text(profile)
            with patch.object(ring_agent.bridge,'EXPERIENCE',path):
                selected=ring_agent.background_for('Explain the Priceline website pipeline')
                self.assertIn('Core stack',selected);self.assertIn('Priceline detail',selected);self.assertNotIn('Mizuho detail',selected)
    def test_code_requests_use_fast_model_but_scenarios_keep_astra(self):
        self.assertEqual(ring_agent.fast_model('Give me the SQL','gpt-6-astra'),'gpt-5.6-sol')
        self.assertEqual(ring_agent.fast_model('Write BigQuery SQL to keep the latest row','gpt-6-astra'),'gpt-5.6-sol')
        self.assertEqual(ring_agent.fast_model('Explain the architecture','gpt-6-astra'),'gpt-6-astra')
        with patch.object(ring_agent.urllib.request,'urlopen',return_value=stream_bytes(['SELECT 1'])) as call:
            list(ring_agent.RingConversation().stream('Write SQL query','gpt-6-astra','fake'))
            self.assertEqual(json.loads(call.call_args.args[0].data)['model'],'gpt-5.6-sol')
if __name__=='__main__':unittest.main()
