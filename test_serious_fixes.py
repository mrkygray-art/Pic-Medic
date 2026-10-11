"""Regression tests for the five serious fixes: Recycle Bin safety, UTF-8 output, verdict severities,
the PowerShell path, and warning-level disk events."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector
import dashboard
import storage_explorer as se
from analyze import analyze

EVENTS_OK = {'status': 'ok', 'data': {'channels': [{'name': 'System', 'status': 'ok', 'events': []}]}}


def events(*ids):
    return {'status': 'ok', 'data': {'channels': [{'name': 'System', 'status': 'ok', 'events': [
        {'Id': i, 'ProviderName': {7: 'disk', 11: 'disk', 18: 'whea-logger', 51: 'disk', 20: 'windowsupdateclient'}[i], 'TimeCreated': '2026-10-10T01:00:00'} for i in ids]}]}}


class TestVerdictSeverities(unittest.TestCase):
    def findings(self, **checks):
        return [(f['severity'], f['title']) for f in analyze({'checks': dict({'event_log_analysis': EVENTS_OK}, **checks)})['findings']]

    def test_clean_pc_has_no_findings(self):
        self.assertEqual(self.findings(memory={'status': 'ok', 'data': {'TotalGB': 16, 'FreeGB': 8}}), [])

    def test_failing_drive_is_high(self):
        self.assertEqual(self.findings(storage_health={'status': 'ok', 'data': [{'FriendlyName': 'SSD', 'HealthStatus': 'Warning'}]})[0][0], 'high')
        reliability = {'status': 'ok', 'data': [{'FriendlyName': 'SSD', 'ReadErrorsUncorrected': 3}]}
        self.assertEqual(self.findings(drive_reliability=reliability)[0][0], 'high')

    def test_warm_nvme_is_not_flagged(self):
        self.assertEqual(self.findings(drive_reliability={'status': 'ok', 'data': [{'FriendlyName': 'SSD', 'Temperature': 68}]}), [])
        self.assertEqual(self.findings(drive_reliability={'status': 'ok', 'data': [{'FriendlyName': 'SSD', 'Temperature': 80}]})[0][0], 'warning')

    def test_event_severity_follows_event_ids(self):
        self.assertEqual(self.findings(event_log_analysis=events(7))[0], ('high', 'Hardware or disk errors in Windows logs'))
        self.assertEqual(self.findings(event_log_analysis=events(51))[0][0], 'warning')
        self.assertEqual(self.findings(event_log_analysis=events(20))[0][0], 'info')

    def test_disk_space_needs_low_gigabytes_too(self):
        disk = lambda size, free: {'status': 'ok', 'data': [{'DeviceID': 'C:', 'SizeGB': size, 'FreeGB': free}]}
        self.assertEqual(self.findings(disks=disk(475, 74)), [])                    # this laptop: 15.6% but 74 GB
        self.assertEqual(self.findings(disks=disk(64, 8))[0][0], 'warning')         # under 10 GB
        self.assertEqual(self.findings(disks=disk(150, 25))[0][0], 'info')          # 16.7% and under 30 GB


class TestRecycleBinSafety(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.file = self.dir / 'video.mp4'
        self.file.write_bytes(b'x' * 4096)
        st = self.file.stat()
        se.TOKENS['window-a'] = {'tok': (str(self.file), 1e18, st.st_size, st.st_mtime_ns)}
        patcher = patch('storage_explorer.allowed', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        se.TOKENS.pop('window-a', None)
        if self.file.exists():
            self.file.unlink()
        self.dir.rmdir()

    def test_too_big_for_recycle_bin_is_refused_and_kept(self):
        with patch('storage_explorer.recycle_bin_limit', return_value={'disabled': False, 'max_bytes': 1024}), \
             patch('storage_explorer.send_to_recycle_bin') as send:
            with self.assertRaisesRegex(RuntimeError, 'larger than the Recycle Bin'):
                se.recycle('tok', 'window-a')
        send.assert_not_called()
        self.assertTrue(self.file.exists())

    def test_disabled_recycle_bin_is_refused(self):
        with patch('storage_explorer.recycle_bin_limit', return_value={'disabled': True, 'max_bytes': None}), \
             patch('storage_explorer.send_to_recycle_bin') as send:
            with self.assertRaisesRegex(RuntimeError, 'turned off'):
                se.recycle('tok', 'window-a')
        send.assert_not_called()

    def test_selections_belong_to_their_window(self):
        with self.assertRaisesRegex(ValueError, 'expired'):
            se.recycle('tok', 'window-b')

    def test_file_still_present_is_reported(self):
        with patch('storage_explorer.recycle_bin_limit', return_value=None), patch('storage_explorer.send_to_recycle_bin'):
            with self.assertRaisesRegex(RuntimeError, 'still in place'):
                se.recycle('tok', 'window-a')

    def test_no_permanent_delete_flags(self):
        import inspect
        source = inspect.getsource(se.send_to_recycle_bin)
        self.assertIn('FOF_ALLOWUNDO|FOF_WANTNUKEWARNING', source)


@unittest.skipUnless(os.name == 'nt', 'Windows only')
class TestWindowsBehaviour(unittest.TestCase):
    def test_powershell_output_keeps_any_language(self):
        result = collector.powershell("[pscustomobject]@{n='Сервер Łódź café ®'} | ConvertTo-Json -Compress")
        self.assertEqual(result, {'status': 'ok', 'data': {'n': 'Сервер Łódź café ®'}})

    def test_every_windows_tool_program_exists(self):
        system32 = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32'
        for key, (_, target) in dashboard.WINDOWS_TOOLS.items():
            if not target.startswith(('ms-settings:', 'windowsdefender:')):
                with self.subTest(tool=key):
                    self.assertTrue((system32 / target).exists(), target)

    def test_junctions_are_detected(self):
        base = Path(tempfile.mkdtemp())
        (base / 'real').mkdir()
        link = base / 'link'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(base / 'real')], capture_output=True)
        try:
            self.assertTrue(se.is_link(link))
            self.assertFalse(se.is_link(base / 'real'))
        finally:
            subprocess.run(['cmd', '/c', 'rmdir', str(link)], capture_output=True)
            (base / 'real').rmdir()
            base.rmdir()

    def test_warning_level_disk_events_are_collected(self):
        with patch('collector.powershell', return_value={'status': 'ok', 'data': {}}) as ps:
            collector.collect_event_logs()
        self.assertIn('Level=3;Id=@(17,19,51,129,153)', ps.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
