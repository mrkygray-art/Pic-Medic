"""Diagnostic coordinator: playbooks, evidence correlation, next tests, and the hand-off to Claude.
Run: python -m unittest discover -p "test_*.py"
"""
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import assistant
import coordinator
import dashboard
import intent_engine


def sig(count, week=0, top=None):
    s = {'Count': count, 'Week': week, 'Last': '2026-10-10T10:00:00'}
    if top:
        s['Top'] = [{'Name': n, 'Count': c} for n, c in top]
    return s


QUIET = {'available': True}
CLEAN = {'event_signals': dict(QUIET), 'crashes': {'available': True, 'BlueScreens': [], 'UnexpectedRestarts': []},
         'disk_health': {'available': True, 'Disks': [{'Name': 'SSD', 'Health': 'Healthy'}], 'Volumes': [{'Drive': 'C:', 'FreeGB': 200, 'SizeGB': 475}]},
         'pending_reboot': {'available': True, 'UptimeDays': 1}, 'updates': {'available': True, 'Failures': []}}


def evidence(**changes):
    r = json.loads(json.dumps(CLEAN))
    for k, v in changes.items():
        r.setdefault(k, {}).update(v) if isinstance(v, dict) else r.__setitem__(k, v)
    return r


class TestPlaybooks(unittest.TestCase):
    def test_symptoms(self):
        cases = {'My computer keeps freezing': 'freeze', 'the laptop gets really hot and the fan is loud': 'overheat', 'wifi keeps dropping': 'network',
                 'chrome keeps crashing': 'app_crash', 'my pc restarts randomly': 'crash', 'battery drains fast': 'battery', 'something is wrong': 'general'}
        for q, kind in cases.items():
            self.assertEqual(coordinator.playbook_for(q), kind, q)

    def test_routing(self):
        self.assertEqual(intent_engine.classify('My computer keeps freezing', {}), {'intent': 'investigate', 'kind': 'freeze', 'scan': 'none'})
        self.assertEqual(intent_engine.classify('my pc restarts randomly', {})['kind'], 'crash')
        self.assertEqual(intent_engine.classify('why did I get a blue screen', {}).get('check'), 'crashes')  # a question, not a problem report
        self.assertEqual(intent_engine.classify('my computer is slow', {})['intent'], 'slow')                  # guided troubleshooting stays


class TestCorrelation(unittest.TestCase):
    def titles(self, kind, r, **kw):
        return [f['title'] for f in coordinator.correlate(kind, r, **kw)]

    def test_nothing_found_recommends_measuring(self):
        self.assertEqual(coordinator.correlate('freeze', evidence()), [])
        self.assertEqual(coordinator.rank_tests('freeze', [])[0]['id'], 'watch')

    def test_graphics_resets_lead_for_freezes(self):
        r = evidence(event_signals={'GpuResets': sig(4, 2), 'Thermal': sig(3)})
        f = coordinator.correlate('freeze', r)
        self.assertEqual(f[0]['title'], 'Graphics driver')
        self.assertEqual(coordinator.rank_tests('freeze', f)[0]['id'], 'deep_scan')

    def test_drive_errors_and_hardware(self):
        r = evidence(event_signals={'StorageResets': sig(2), 'Hardware': sig(1)})
        titles = self.titles('freeze', r)
        self.assertIn('Drive', titles)
        self.assertIn('Hardware errors', titles)

    def test_heat_and_low_memory(self):
        r = evidence(event_signals={'Thermal': sig(17, 7), 'LowMemory': sig(3, 3)})
        f = coordinator.correlate('freeze', r, perf={'cpu': 40, 'memory': 91})
        self.assertEqual({x['title'] for x in f[:2]}, {'Heat or power limits', 'Memory running out'})
        self.assertIn('91%', next(x for x in f if x['title'] == 'Memory running out')['plain'])

    def test_one_program_behind_the_hangs(self):
        r = evidence(event_signals={'AppHangs': sig(6, 2, [('Photoshop.exe', 5), ('chrome.exe', 1)])})
        f = coordinator.correlate('freeze', r)
        self.assertIn('Photoshop.exe', f[0]['plain'])

    def test_blue_screen_with_known_driver(self):
        r = evidence(crashes={'BlueScreens': [{'Code': '0x00000116', 'name': 'VIDEO_TDR_FAILURE', 'Driver': {'driver': 'nvlddmkm.sys'}}]})
        f = coordinator.correlate('crash', r)
        self.assertIn('nvlddmkm.sys', f[0]['plain'])
        self.assertEqual(f[0]['tests'], ['device_manager'])

    def test_hard_freezes_without_blue_screen(self):
        self.assertIn('Hard freezes or power loss', self.titles('freeze', evidence(crashes={'UnexpectedRestarts': ['2026-10-09T08:00:00']})))

    def test_network_and_battery_playbooks(self):
        self.assertEqual(self.titles('network', evidence(event_signals={'WifiDrops': sig(3)})), ['Wi-Fi'])
        r = evidence(battery={'available': True, 'HealthPercent': 55})
        self.assertIn('Battery wear', self.titles('battery', r, perf={'cpu': 45, 'memory': 50}))

    def test_deep_scan_already_run_is_not_suggested_again(self):
        f = coordinator.correlate('freeze', evidence(event_signals={'StorageResets': sig(1)}))
        self.assertNotIn('deep_scan', [t['id'] for t in coordinator.rank_tests('freeze', f, deep={'finished': 'x'})])


class TestInvestigate(unittest.TestCase):
    def run_it(self):
        data = evidence(event_signals={'AppHangs': sig(4, 1, [('SecretApp.exe', 4)]), 'Thermal': sig(5, 2)})
        with patch('system_checks.check', side_effect=lambda name: data.get(name, {'available': False})), \
             patch('today.quick_performance', return_value={'cpu': 20.0, 'memory': 60.0, 'disk': 1.0, 'total_gb': 16, 'samples': 3}), \
             patch('system_checks.deep_scan', return_value=None), patch('timeline.summary', return_value={'items': []}):
            return coordinator.investigate('My computer keeps freezing')

    def test_result_and_text(self):
        r = self.run_it()
        self.assertEqual(r['kind'], 'freeze')
        self.assertIn('performance', [x['id'] for x in r['routines']])
        self.assertTrue(r['findings'] and r['next_tests'])
        text = coordinator.describe(r)
        self.assertIn('What the evidence points to', text)
        self.assertIn('Next test:', text)

    def test_claude_never_sees_program_names(self):
        self.assertNotIn('SecretApp', json.dumps(self.run_it()['cloud']))


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        cls.server.demo = True
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def post(self, path, body):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps(body).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'X-PC-Medic-Token': dashboard.TOKEN, 'Host': f'127.0.0.1:{self.port}'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    def test_investigation_then_claude_gets_the_evidence(self):
        dashboard.ACTIVITY.update(kind=None, owner=None, until=0.0)
        fake = {'kind': 'freeze', 'title': 'Freezing or not responding', 'question': 'q', 'routines': [], 'findings': [], 'next_tests': [], 'at': 'now', 'cloud': {'findings': ['EVIDENCE']}}
        with patch('coordinator.investigate', return_value=fake):
            r = self.post('/api/coordinate', {'question': 'My computer keeps freezing', 'kind': 'freeze', 'owner': 'window-coord-1'})
        self.assertNotIn('cloud', r)
        self.assertIsNone(dashboard.ACTIVITY['owner'])  # the slot is released
        with patch('settings.key_for_use', return_value=('k', 'environment')), patch('assistant.JOBS.start', return_value='job1') as start:
            self.post('/api/assistant', {'question': 'My computer keeps freezing', 'consent': True, 'investigation_id': r['id']})
        self.assertIn('EVIDENCE', start.call_args[0][1])
        self.assertIn('not instructions', start.call_args[0][1])


class TestClaudeCoordinates(unittest.TestCase):
    def test_next_test_is_returned_and_tools_stay_read_only(self):
        assistant.CONVERSATIONS = assistant.Conversations()
        replies = [SimpleNamespace(content=[SimpleNamespace(type='tool_use', id='t1', name='investigate_problem', input={'problem': 'freeze'})], stop_reason='tool_use', model='m',
                                   usage=SimpleNamespace(server_tool_use=SimpleNamespace(web_search_requests=0))),
                   SimpleNamespace(content=[SimpleNamespace(type='tool_use', id='t2', name='recommend_next_test', input={'test': 'watch', 'reason': 'Catch the memory spike.'})], stop_reason='tool_use', model='m',
                                   usage=SimpleNamespace(server_tool_use=SimpleNamespace(web_search_requests=0))),
                   SimpleNamespace(content=[SimpleNamespace(type='text', text='Most likely low memory.', citations=None)], stop_reason='end_turn', model='m',
                                   usage=SimpleNamespace(server_tool_use=SimpleNamespace(web_search_requests=0)))]
        client = MagicMock()
        client.beta.messages.create.side_effect = lambda **kw: replies.pop(0)
        with patch('anthropic.Anthropic', return_value=client), patch('settings.key_for_use', return_value=('k', 'environment')), patch('settings.record_use'), \
             patch('coordinator.investigate', return_value={'cloud': {'findings': []}}) as inv:
            r = assistant.ask(None, 'My computer keeps freezing')
        inv.assert_called_once_with('', False, 'freeze')
        self.assertEqual(r['next_tests'], [{'id': 'watch', 'label': 'Catch it with a Performance Watch', 'why': 'Catch the memory spike.'}])
        with self.assertRaises(ValueError):
            assistant.run_tool('recommend_next_test', {'test': 'format_drive'})
        self.assertEqual(assistant.run_tool('lookup_error_code', {'code': '0x80070070'})[0]['name'], 'ERROR_DISK_FULL')


if __name__ == '__main__':
    unittest.main()
