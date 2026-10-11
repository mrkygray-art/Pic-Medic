"""Key sources, the 10-question trial, update checks, and reliable assistant jobs (no network, no cost)."""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import assistant
import settings


class TestKeysAndTrial(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = patch('settings.DATA_FILE', os.path.join(self.dir, 'settings.json'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_source_order_saved_then_environment_then_trial(self):
        env = {'ANTHROPIC_API_KEY': 'env-key', 'PCMEDIC_TRIAL_ANTHROPIC_API_KEY': 'trial-key'}
        with patch.dict('os.environ', env, clear=True):
            with patch('settings.load_key', return_value='saved-key'):
                self.assertEqual(settings.resolve('anthropic'), ('saved-key', 'saved'))
            with patch('settings.load_key', return_value=None):
                self.assertEqual(settings.resolve('anthropic'), ('env-key', 'environment'))
        with patch.dict('os.environ', {'PCMEDIC_TRIAL_ANTHROPIC_API_KEY': 'trial-key'}, clear=True), patch('settings.load_key', return_value=None):
            self.assertEqual(settings.resolve('anthropic'), ('trial-key', 'trial'))

    def test_trial_allows_ten_questions_then_asks_for_own_key(self):
        with patch.dict('os.environ', {'PCMEDIC_TRIAL_ANTHROPIC_API_KEY': 'trial-key'}, clear=True), patch('settings.load_key', return_value=None):
            for _ in range(settings.TRIAL_LIMIT):
                key, source = settings.key_for_use('anthropic')
                settings.record_use(source)
            with self.assertRaisesRegex(settings.TrialExhausted, 'Add your own'):
                settings.key_for_use('anthropic')
            self.assertEqual(settings.summary()['trial'], {'limit': 10, 'used': 10, 'remaining': 0})
            self.assertFalse(settings.available('anthropic'))

    def test_own_keys_are_never_counted(self):
        settings.record_use('environment')
        settings.record_use('saved')
        self.assertEqual(settings.trial_uses(), 0)

    def test_summary_never_contains_keys(self):
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'sk-ant-secret-value'}, clear=True), patch('settings.load_key', return_value=None):
            self.assertNotIn('sk-ant-secret-value', repr(settings.summary()))

    def test_key_format_checked_before_any_network_call(self):
        with patch('urllib.request.urlopen') as net, self.assertRaisesRegex(ValueError, 'does not look like'):
            settings.verify_key('anthropic', 'not-a-key')
        net.assert_not_called()

    def test_update_check(self):
        release = lambda tag, url: (lambda _: {'tag_name': tag, 'html_url': url})
        with patch('settings.UPDATE_REPO', 'ky/pc-medic'), patch('settings.VERSION', '1.17.0'):
            newer = settings.check_for_update(fetch=release('v1.18.0', 'https://github.com/ky/pc-medic/releases/tag/v1.18.0'))
            same = settings.check_for_update(fetch=release('v1.17.0', 'https://github.com/ky/pc-medic/releases/tag/v1.17.0'))
            hostile = settings.check_for_update(fetch=release('v9.9.9', 'https://evil.example/download'))
            settings.set_update_checks(False)
            off = settings.check_for_update(fetch=lambda _: self.fail('should not fetch'))
        self.assertEqual((newer['available'], newer['latest']), (True, '1.18.0'))
        self.assertFalse(same['available'])
        self.assertFalse(hostile['available'])
        self.assertEqual(off, {'enabled': False})

    def test_no_repo_means_no_update_check(self):
        with patch('settings.UPDATE_REPO', ''):
            self.assertEqual(settings.check_for_update(fetch=lambda _: self.fail('should not fetch')), {'enabled': False})


def reply(stop, *blocks):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, model='claude-opus-5-5', usage=SimpleNamespace(server_tool_use=None))


def tool(i, name, args):
    return SimpleNamespace(type='tool_use', id=i, name=name, input=args)


def text(t):
    return SimpleNamespace(type='text', text=t, citations=None)


class TestReliableJobs(unittest.TestCase):
    def setUp(self):
        assistant.CONVERSATIONS = assistant.Conversations()
        self.client = MagicMock()
        self.sent, self.replies = [], []

        def create(**kwargs):
            self.sent.append([dict(m) for m in kwargs['messages']])
            return self.replies.pop(0)
        self.client.beta.messages.create.side_effect = create
        for target, value in (('anthropic.Anthropic', self.client), ('settings.key_for_use', ('k', 'environment')), ('settings.record_use', None)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_duplicate_tool_calls_run_once_and_tools_run_in_parallel(self):
        self.replies = [reply('tool_use', tool('a', 'get_performance_snapshot', {}), tool('b', 'run_check', {'check': 'battery'})),
                        reply('tool_use', tool('c', 'get_performance_snapshot', {})),
                        reply('end_turn', text('Done.'))]
        calls = []

        def slow(name, args, demo):
            calls.append(name)
            time.sleep(0.3)
            return {}, name
        started = time.monotonic()
        with patch('assistant.run_tool', side_effect=slow):
            r = assistant.ask(None, 'Why slow?')
        self.assertEqual(sorted(calls), ['get_performance_snapshot', 'run_check'])  # the repeat came from the cache
        self.assertLess(time.monotonic() - started, 0.55)                            # the two tools ran side by side
        self.assertEqual(r['answer'], 'Done.')

    def test_slow_tool_times_out_instead_of_hanging(self):
        self.replies = [reply('tool_use', tool('a', 'get_recent_errors', {})), reply('end_turn', text('Partial.'))]
        with patch('assistant.TOOL_TIMEOUT', 0.2), patch('assistant.run_tool', side_effect=lambda *a: time.sleep(1.5) or ({}, 'x')):
            r = assistant.ask(None, 'Is something wrong?')
        result = self.sent[1][-1]['content'][0]
        self.assertTrue(result['is_error'])
        self.assertIn('timed out', result['content'])
        self.assertEqual(r['answer'], 'Partial.')

    def test_cancel_keeps_conversation_unchanged(self):
        self.replies = [reply('end_turn', text('First.'))]
        conv = assistant.ask(None, 'one')['conversation_id']
        before = list(assistant.CONVERSATIONS.items[conv]['messages'])
        self.replies = [reply('tool_use', tool('a', 'get_network_status', {}))]
        checks = {'n': 0}

        def cancelled():
            checks['n'] += 1
            return checks['n'] > 1  # the user cancels after Claude's first reply
        with patch('assistant.run_tool', return_value=({}, 'x')), self.assertRaises(assistant.Cancelled):
            assistant.ask(conv, 'two', cancelled=cancelled)
        self.assertEqual(assistant.CONVERSATIONS.items[conv]['messages'], before)

    def test_job_reports_progress_and_result(self):
        jobs = assistant.Jobs()

        def fake(conv, question, demo, progress, cancelled):
            progress('Read computer model and hardware…')
            return {'answer': 'ok'}
        with patch('assistant.ask', side_effect=fake):
            job_id = jobs.start(None, 'q')
            for _ in range(50):
                if jobs.get(job_id)['status'] != 'running':
                    break
                time.sleep(0.02)
        job = jobs.get(job_id)
        self.assertEqual((job['status'], job['result'], job['steps']), ('done', {'answer': 'ok'}, ['Read computer model and hardware…']))


if __name__ == '__main__':
    unittest.main()
