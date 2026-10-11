"""Claude investigator loop with a fake Anthropic client (no network, no cost)."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import assistant


def reply(stop, *blocks, searches=0):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, model='claude-opus-5-5',
                           usage=SimpleNamespace(server_tool_use=SimpleNamespace(web_search_requests=searches)))

text = lambda t, citations=None: SimpleNamespace(type='text', text=t, citations=citations)
tool = lambda i, name, args: SimpleNamespace(type='tool_use', id=i, name=name, input=args)


class TestLoop(unittest.TestCase):
    def setUp(self):
        assistant.CONVERSATIONS = assistant.Conversations()
        self.client = MagicMock()
        self.sent = []  # copies of `messages` at each call; the live list keeps growing afterwards
        self.replies = []
        def create(**kwargs):
            self.sent.append([dict(m) for m in kwargs['messages']])
            item = self.replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        self.client.beta.messages.create.side_effect = create
        for target, value in (('anthropic.Anthropic', self.client), ('settings.key_for_use', ('test-key', 'environment'))):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_runs_requested_tools_then_answers(self):
        self.replies = [
            reply('tool_use', text('Let me check.'), tool('t1', 'run_check', {'check': 'battery'})),
            reply('end_turn', text('Your battery is at 95% of its original capacity.')),
        ]
        with patch('assistant.run_tool', return_value=({'HealthPercent': 95}, 'Checked battery health')) as run:
            r = assistant.ask(None, 'How is my battery?')
        run.assert_called_once_with('run_check', {'check': 'battery'}, False)
        self.assertEqual(r['answer'], 'Your battery is at 95% of its original capacity.')
        self.assertEqual(r['tools_used'], ['Checked battery health'])
        self.assertEqual(self.sent[1][-1]['content'][0], {'type': 'tool_result', 'tool_use_id': 't1', 'content': '{"HealthPercent": 95}'})

    def test_follow_up_continues_same_conversation(self):
        self.replies = [reply('end_turn', text('A')), reply('end_turn', text('B'))]
        first = assistant.ask(None, 'Should I upgrade this laptop?')
        second = assistant.ask(first['conversation_id'], 'yes')
        self.assertEqual(first['conversation_id'], second['conversation_id'])
        self.assertEqual([m['role'] for m in self.sent[1]], ['user', 'assistant', 'user'])
        self.assertEqual(self.sent[1][-1]['content'], 'yes')

    def test_failed_tool_is_reported_to_claude_not_raised(self):
        self.replies = [reply('tool_use', tool('t1', 'get_recent_errors', {})), reply('end_turn', text('Could not read the logs.'))]
        with patch('assistant.run_tool', side_effect=OSError('denied')):
            r = assistant.ask(None, 'Is something wrong?')
        result = self.sent[1][-1]['content'][0]
        self.assertTrue(result['is_error'])
        self.assertEqual(r['tools_used'], [])

    def test_api_failure_leaves_history_replayable(self):
        self.replies = [reply('end_turn', text('A')), RuntimeError('boom'), reply('end_turn', text('C'))]
        conv = assistant.ask(None, 'one')['conversation_id']
        with self.assertRaises(RuntimeError):
            assistant.ask(conv, 'two')
        assistant.ask(conv, 'three')
        sent = self.sent[2]
        self.assertEqual([m['content'] if isinstance(m['content'], str) else 'assistant' for m in sent], ['one', 'assistant', 'three'])

    def test_step_limit_forces_an_answer(self):
        loops = [reply('tool_use', tool(f't{i}', 'get_performance_snapshot', {})) for i in range(assistant.MAX_STEPS)]
        self.replies = loops + [reply('end_turn', text('Here is what I found.'))]
        with patch('assistant.run_tool', return_value=({}, 'Measured CPU, memory and disk use')):
            r = assistant.ask(None, 'Why is it slow?')
        self.assertEqual(self.client.beta.messages.create.call_args_list[-1].kwargs['tool_choice'], {'type': 'none'})
        self.assertEqual(r['answer'], 'Here is what I found.')

    def test_request_shape_and_citations(self):
        cite = SimpleNamespace(type='web_search_result_location', url='https://psref.lenovo.com/x', title='PSREF', cited_text='two slots')
        self.replies = [reply('end_turn', text('It has two slots.', [cite]), searches=1)]
        r = assistant.ask(None, 'Can I add RAM?')
        kwargs = self.client.beta.messages.create.call_args.kwargs
        self.assertEqual((kwargs['model'], kwargs['fallbacks']), ('claude-opus-5-5', 'default'))
        self.assertNotIn('tool_choice', kwargs)
        self.assertEqual(r['answer'], 'It has two slots. [1]')
        self.assertEqual(r['sources'][0]['url'], 'https://psref.lenovo.com/x')
        self.assertIn('Searched the web', r['tools_used'])


class TestTools(unittest.TestCase):
    def test_only_allowlisted_tools_run(self):
        with self.assertRaises(ValueError):
            assistant.run_tool('run_shell', {'command': 'del C:\\'})
        with self.assertRaises(ValueError):
            assistant.run_tool('run_check', {'check': 'format_disk'})

    def test_every_tool_is_read_only_and_documented(self):
        names = {t['name'] for t in assistant.TOOLS}
        self.assertEqual(names, {'get_computer_overview', 'run_check', 'get_recent_errors', 'get_latest_health_check', 'get_performance_snapshot', 'get_network_status', 'web_search'})
        self.assertEqual(set(assistant.TOOLS[1]['input_schema']['properties']['check']['enum']), set(assistant.system_checks.SCRIPTS))


if __name__ == '__main__':
    unittest.main()
