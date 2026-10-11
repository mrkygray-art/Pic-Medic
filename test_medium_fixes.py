"""Regression tests for the medium fixes: disk busy range, Windows tool errors, registry safety,
Windows 11 naming, and the ChatGPT fallback prompt/privacy."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import ai_engine
import dashboard
from dashboard import DEMO
from performance_diagnostics import parse_metrics


class TestDiskBusy(unittest.TestCase):
    def test_busy_comes_from_idle_time_and_stays_in_range(self):
        self.assertEqual(parse_metrics({'disk_busy_percent': 132, 'disk_idle_percent': 40})['disk_busy_percent'], 60.0)
        self.assertEqual(parse_metrics({'disk_busy_percent': 132})['disk_busy_percent'], 100.0)   # older data without idle time
        self.assertEqual(parse_metrics({'disk_idle_percent': 100})['disk_busy_percent'], 0.0)

    def test_history_accepts_capped_value(self):
        entry = dashboard.safe_history_entry({'stats': {'disk_peak': parse_metrics({'disk_busy_percent': 132})['disk_busy_percent']}})
        self.assertEqual(entry['metrics']['disk_peak'], 100.0)


class TestWindowsToolErrors(unittest.TestCase):
    def launch_with(self, code):
        shell = MagicMock()
        shell.ShellExecuteW.return_value = code
        with patch('ctypes.WinDLL', return_value=shell):
            try:
                dashboard.shell_open_windows('taskmgr.exe', elevate_if_required=True)
            finally:
                verbs = [c.args[1] for c in shell.ShellExecuteW.call_args_list]
        return verbs

    def test_cancelled_uac_is_not_retried(self):
        with self.assertRaisesRegex(RuntimeError, 'Administrator approval was declined'):
            self.launch_with(5)

    def test_null_result_is_an_error_not_a_crash(self):
        with self.assertRaisesRegex(RuntimeError, 'out of memory'):
            self.launch_with(None)

    def test_success(self):
        shell = MagicMock()
        shell.ShellExecuteW.return_value = 42
        with patch('ctypes.WinDLL', return_value=shell):
            dashboard.shell_open_windows('taskmgr.exe')
        self.assertEqual([c.args[1] for c in shell.ShellExecuteW.call_args_list], ['open'])

    def test_defender_scan_options_opens_scan_page(self):
        self.assertEqual(dashboard.WINDOWS_TOOLS['security-offline-scan'][1], 'windowsdefender://threat')


@unittest.skipUnless(os.name == 'nt', 'Windows registry')
class TestRegistrySafety(unittest.TestCase):
    def test_control_set_aliases_are_blocked(self):
        for path in (r'SYSTEM\ControlSet001\Control\Lsa', r'\SYSTEM\ControlSet002\Control\Lsa', r'system\controlset001\control\lsa\msv1_0'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Protected'):
                dashboard.registry_lookup('HKLM', path, 'LimitBlankPasswordUse')

    def test_password_values_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'passwords or secrets'):
            dashboard.registry_lookup('HKLM', r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon', 'DefaultPassword')

    def test_ordinary_values_still_work(self):
        self.assertTrue(dashboard.registry_lookup('HKLM', r'SOFTWARE\Microsoft\Windows NT\CurrentVersion', 'ProductName')['value'])

    def test_windows_11_is_named_correctly(self):
        import platform
        if int(platform.version().split('.')[-1]) >= 22000:
            self.assertIn('Windows 11', dashboard.windows_edition())


class TestChatGPTFallback(unittest.TestCase):
    def test_one_request_no_tools_general_prompt(self):
        reply = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'A charger answer.'}]}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'k'}), patch('ai_engine.post', return_value=reply) as post:
            r = ai_engine.ask('openai', 'I need a new charger', DEMO, True)
        self.assertEqual(r['answer'], 'A charger answer.')
        payload = post.call_args.args[2]
        self.assertNotIn('tools', payload)
        self.assertEqual(payload['instructions'], ai_engine.CHAT_SYSTEM)
        self.assertIn('use only if relevant', payload['input'][0]['content'])
        self.assertEqual(post.call_count, 1)

    def test_empty_or_incomplete_answers_are_errors(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'k'}):
            with patch('ai_engine.post', return_value={'status': 'incomplete', 'output': []}), self.assertRaisesRegex(RuntimeError, 'ran out of space'):
                ai_engine.ask('openai', 'q', DEMO, True)
            with patch('ai_engine.post', return_value={'output': []}), self.assertRaisesRegex(RuntimeError, 'no answer'):
                ai_engine.ask('openai', 'q', DEMO, True)

    def test_drive_names_are_not_sent(self):
        report = {**DEMO, 'checks': {**DEMO['checks'], 'storage_health': {'status': 'ok', 'data': [{'FriendlyName': 'Samsung SSD 980 PRO', 'HealthStatus': 'Warning'}]}}}
        summary = json.dumps(ai_engine.safe_summary(report))
        self.assertNotIn('Samsung', summary)
        self.assertIn('Storage health status', summary)


if __name__ == '__main__':
    unittest.main()
