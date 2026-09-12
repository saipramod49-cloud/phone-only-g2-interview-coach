import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from bridge import Conversation, make_server, pages, plain_text, system_prompt


class BridgeTests(unittest.TestCase):
    def test_bullets_survive_display_formatting(self):
        text = '* Use **stable IDs**.\n* Apply `MERGE`.\n* Reconcile totals.'
        self.assertEqual(pages(text), ['- Use stable IDs.\n- Apply MERGE.\n- Reconcile totals.'])

    def test_experience_reloaded_and_missing_profile_falls_back(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'experience.md'
            with patch('bridge.EXPERIENCE', path):
                self.assertNotIn('<candidate_background>', system_prompt())
                path.write_text('Current employer: Mizuho. Prior employer: Priceline.')
                self.assertIn('Current employer: Mizuho.', system_prompt())
                path.write_text('Updated candidate fact.')
                self.assertIn('Updated candidate fact.', system_prompt())
                self.assertNotIn('Current employer: Mizuho.', system_prompt())

    def test_pages_preserve_content_and_fit_display(self):
        text = '**Important** ' + ('Stable event IDs prevent duplicate payments. ' * 60)
        result = pages(text)
        self.assertTrue(all(len(p) <= 400 for p in result))
        import re
        reconstructed = ' '.join(re.sub(r' \(\d+/\d+\)( Say continue\.)?$', '', p) for p in result)
        self.assertEqual(' '.join(reconstructed.split()), ' '.join(plain_text(text).split()))

    def test_whole_bullets_avoid_orphan_continuation(self):
        text = '- ' + 'First complete point. ' * 8 + '\n- ' + 'Second complete point. ' * 8 + '\n- Compact periodically.'
        result = pages(text)
        self.assertEqual(len(result), 2)
        self.assertIn('- Compact periodically.', result[-1])
        self.assertTrue(result[-1].startswith('- Second'))
        self.assertTrue(all(len(p) <= 400 for p in result))

    def test_oversized_bullet_is_balanced_and_preserved(self):
        import re
        text = '- ' + 'Bounded queues prevent memory growth. ' * 10 + 'Compact periodically.'
        result = pages(text)
        bodies = [re.sub(r' \(\d+/\d+\)( Say continue\.)?$', '', p) for p in result]
        self.assertTrue(all(100 < len(p) <= 360 for p in bodies))
        self.assertEqual(' '.join(' '.join(bodies).split()), ' '.join(text.split()))

    def test_continue_does_not_call_model(self):
        c = Conversation()
        text = 'Deduplicate with stable identifiers. ' * 25
        with patch('bridge.complete', return_value=(text, {})) as mocked:
            first, _ = c.ask('How?', 'test', 'test')
            second, meta = c.ask('Continue.', 'test', 'test')
            self.assertIn('(1/', first)
            self.assertIn('(2/', second)
            self.assertTrue(meta['cached_page'])
            self.assertEqual(mocked.call_count, 1)

    def test_auth_validation_and_response_contract(self):
        server = make_server(0, 'test', {'bridge_token': 'private-test-token', 'api_key': 'unused'})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
        try:
            req = urllib.request.Request(url, data=b'{}', headers={'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req)
            self.assertEqual(err.exception.code, 401)
            with patch('bridge.complete', return_value=('A correct short answer.', {})):
                req = urllib.request.Request(url, data=json.dumps({'messages':[{'role':'user','content':'Test'}]}).encode(),
                    headers={'Content-Type':'application/json','Authorization':'Bearer private-test-token'})
                with urllib.request.urlopen(req) as response:
                    data = json.load(response)
                self.assertEqual(data['choices'][0]['message']['content'], 'A correct short answer.')
        finally:
            server.shutdown()
            server.server_close()

if __name__ == '__main__':
    unittest.main()
