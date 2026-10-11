"""Regression tests for the DNS-rebinding, packaged-collector and cross-window scan-lock fixes.
Run: python -m unittest discover -p "test_*.py"
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import dashboard


class LocalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        cls.server.demo = True
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        dashboard.ACTIVITY.update(kind=None, owner=None, until=0.0)

    def call(self, path, body=None, host=None, origin=None):
        headers = {'Content-Type': 'application/json', 'X-PC-Medic-Token': dashboard.TOKEN, 'Host': host or f'127.0.0.1:{self.port}'}
        if origin:
            headers['Origin'] = origin
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)


class TestDnsRebinding(LocalServer):
    def test_foreign_host_gets_no_token(self):
        status, body = self.call('/api/report', host=f'evil.example:{self.port}')
        self.assertEqual(status, 403)
        self.assertNotIn('csrf', body)

    def test_foreign_host_cannot_post_even_with_token(self):
        self.assertEqual(self.call('/api/intent', {'question': 'hi'}, host=f'evil.example:{self.port}', origin=f'http://evil.example:{self.port}')[0], 403)

    def test_foreign_origin_with_local_host_is_rejected(self):
        self.assertEqual(self.call('/api/intent', {'question': 'hi'}, origin='http://evil.example')[0], 403)

    def test_local_names_are_accepted(self):
        self.assertEqual(self.call('/api/report')[0], 200)
        self.assertEqual(self.call('/api/report', host=f'localhost:{self.port}')[0], 200)
        self.assertEqual(self.call('/api/intent', {'question': 'hi'}, origin=f'http://127.0.0.1:{self.port}')[0], 200)


class TestOneDiagnosticAtATime(LocalServer):
    A, B = 'window-aaaa-1111', 'window-bbbb-2222'

    def test_second_window_is_blocked_until_release(self):
        self.assertEqual(self.call('/api/activity', {'action': 'start', 'kind': 'watch', 'owner': self.A})[0], 200)
        status, body = self.call('/api/activity', {'action': 'start', 'kind': 'health', 'owner': self.B})
        self.assertEqual(status, 409)
        self.assertIn('Performance Watch is already running', body['error'])
        for path in ('/api/scan', '/api/performance-sample', '/api/process-memory'):
            with self.subTest(path=path):
                self.assertEqual(self.call(path, {'owner': self.B})[0], 409)
                self.assertEqual(self.call(path, {})[0], 409)
        self.assertEqual(self.call('/api/performance-sample', {'owner': self.A})[0], 200)
        self.call('/api/activity', {'action': 'end', 'owner': self.B})  # another window cannot release it
        self.assertEqual(self.call('/api/activity', {'action': 'start', 'kind': 'health', 'owner': self.B})[0], 409)
        self.call('/api/activity', {'action': 'end', 'owner': self.A})
        self.assertEqual(self.call('/api/activity', {'action': 'start', 'kind': 'health', 'owner': self.B})[0], 200)

    def test_abandoned_lease_expires(self):
        with patch('dashboard.time.monotonic', return_value=1000.0):
            self.assertIsNone(dashboard.activity_conflict(self.A, 'watch'))
            self.assertEqual(dashboard.activity_conflict(self.B, 'health'), 'A Performance Watch')
        with patch('dashboard.time.monotonic', return_value=1000.0 + dashboard.LEASE_SECONDS + 1):
            self.assertIsNone(dashboard.activity_conflict(self.B, 'health'))

    def test_samples_renew_the_lease(self):
        with patch('dashboard.time.monotonic', return_value=1000.0):
            dashboard.activity_conflict(self.A, 'watch')
        with patch('dashboard.time.monotonic', return_value=1080.0):
            self.assertIsNone(dashboard.activity_conflict(self.A))  # a sample 80s later
        with patch('dashboard.time.monotonic', return_value=1150.0):
            self.assertEqual(dashboard.activity_conflict(self.B, 'health'), 'A Performance Watch')

    def test_rejects_bad_requests(self):
        self.assertEqual(self.call('/api/activity', {'action': 'start', 'kind': 'watch', 'owner': 'x'})[0], 400)
        self.assertEqual(self.call('/api/activity', {'action': 'start', 'kind': 'reboot', 'owner': self.A})[0], 400)


class TestPackagedCollector(unittest.TestCase):
    def test_source_run_uses_collector_script(self):
        with patch('dashboard.FROZEN', False):
            cmd = dashboard.collector_command()
        self.assertTrue(cmd[1].endswith('collector.py'))

    def test_exe_relaunches_itself_in_collector_mode(self):
        with patch('dashboard.FROZEN', True):
            self.assertEqual(dashboard.collector_command()[1:3], ['--run-collector', '--output'])

    def test_collector_mode_dispatches_before_server_starts(self):
        with patch.object(sys, 'argv', ['PCMedic.exe', '--run-collector', '--output', 'x.json']), \
             patch('collector.main', return_value=0) as collect, patch('dashboard.ThreadingHTTPServer') as server:
            dashboard.main()
            self.assertEqual(sys.argv, ['PCMedic.exe', '--output', 'x.json'])
        collect.assert_called_once()
        server.assert_not_called()


if __name__ == '__main__':
    unittest.main()
