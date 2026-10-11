"""1.18.0: the Today screen, two voices (Home and Technician) and the app window.
Run: python -m unittest discover -p "test_*.py"
"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import dashboard
import system_checks
import today
import troubleshooter

GOOD_DISK = {'available': True, 'Disks': [{'Name': 'Micron 512', 'MediaType': 'SSD', 'BusType': 'NVMe', 'SizeGB': 477, 'Health': 'Healthy', 'Status': 'OK',
                                           'ReadErrorsUncorrected': 0, 'WriteErrorsUncorrected': 0}],
             'Volumes': [{'Drive': 'C:', 'FreeGB': 74.0, 'SizeGB': 474.7}]}
BATTERY = {'available': True, 'Present': True, 'Model': 'L22D4PA0', 'FullChargeCapacity_mWh': 56800, 'DesignCapacity_mWh': 60000,
           'HealthPercent': 95, 'CycleCount': 26, 'OnAC': True, 'ChargePercent': 99}
UPDATES = {'available': True, 'SuccessCount': 40, 'FailureCount': 0, 'Failures': []}
CRASHES = {'available': True, 'BlueScreens': [], 'UnexpectedRestarts': [], 'DirtyShutdowns': 0, 'MinidumpCount': 0}
REBOOT = {'available': True, 'ComponentServicing': False, 'WindowsUpdate': False}
PERF = {'cpu': 12.0, 'memory': 55.0, 'disk': 3.0, 'total_gb': 15.7, 'samples': 3}


class TestTiles(unittest.TestCase):
    def test_healthy_laptop(self):
        tiles = [today.speed_tile(PERF), today.storage_tile(GOOD_DISK), today.battery_tile(BATTERY),
                 today.updates_tile(UPDATES, REBOOT), today.stability_tile(CRASHES)]
        self.assertEqual([t['state'] for t in tiles], ['good'] * 5)
        self.assertEqual(today.verdict(tiles), ('Your PC looks healthy', 'Everything PC Medic checked looks good.'))
        for t in tiles:
            self.assertTrue(t['plain'] and t['tech'], t)

    def test_battery_wear_and_desktop(self):
        worn = dict(BATTERY, HealthPercent=52)
        t = today.battery_tile(worn)
        self.assertEqual(t['state'], 'attention')
        self.assertEqual(t['ask'], 'I need a replacement battery')
        desktop = today.battery_tile({'available': True, 'Present': False})
        self.assertEqual((desktop['name'], desktop['state']), ('Power', 'good'))

    def test_storage_full_opens_explorer_and_failing_drive_is_a_problem(self):
        full = json.loads(json.dumps(GOOD_DISK)); full['Volumes'][0]['FreeGB'] = 6.0
        t = today.storage_tile(full)
        self.assertEqual((t['state'], t['open'], t['ask']), ('attention', 'explorer', None))
        bad = json.loads(json.dumps(GOOD_DISK)); bad['Disks'][0]['ReadErrorsUncorrected'] = 4
        self.assertEqual(today.storage_tile(bad)['state'], 'problem')
        title, _ = today.verdict([today.storage_tile(bad), today.speed_tile(PERF)])
        self.assertEqual(title, 'Something needs attention now')

    def test_updates(self):
        self.assertEqual(today.updates_tile(UPDATES, dict(REBOOT, WindowsUpdate=True))['state'], 'attention')
        store_only = dict(UPDATES, Failures=[{'Error': '0x80073D02'}] * 3)
        self.assertIn('app updates', today.updates_tile(store_only, REBOOT)['plain'])
        real = dict(UPDATES, Failures=[{'Error': '0x8024200B'}, {'Error': '0x80073D02'}])
        self.assertTrue(today.updates_tile(real, REBOOT)['plain'].startswith('1 update didn'))

    def test_stability(self):
        self.assertEqual(today.stability_tile(dict(CRASHES, BlueScreens=[{'Code': '0x9F'}]))['state'], 'attention')
        once = today.stability_tile(dict(CRASHES, UnexpectedRestarts=[{}]))
        self.assertEqual(once['state'], 'note')
        self.assertIn('once', once['plain'])

    def test_unavailable_checks_do_not_crash(self):
        off = {'available': False, 'reason': 'test'}
        tiles = [today.speed_tile(None), today.storage_tile(off), today.battery_tile(off), today.updates_tile(off, off), today.stability_tile(off)]
        self.assertTrue(all(t['state'] in today.RANK for t in tiles))

    def test_cache_and_refresh(self):
        today._cache.update(at=0.0, data=None)
        with patch('today.build', return_value={'tiles': []}) as build:
            today.get(); today.get()
            self.assertEqual(build.call_count, 1)
            today.get(refresh=True)
            self.assertEqual(build.call_count, 2)
        today._cache.update(at=0.0, data=None)


class TestTechnicalVoice(unittest.TestCase):
    def test_battery_line_tolerates_missing_capacity(self):
        line = system_checks.describe_technical('battery', dict(BATTERY, FullChargeCapacity_mWh=None))
        self.assertIn('? / 60,000 mWh', line)

    def test_troubleshooter_findings_have_tech_text(self):
        m = {'memory': 92, 'memory_total_gb': 16, 'cpu': 70, 'disk_busy': 10,
             'processes': [{'name': 'chrome', 'ram_gb': 5.0, 'cpu': 40, 'io': 1, 'count': 20}], 'startup': [], 'reboot': {}, 'disk': {}, 'power': {}}
        found = troubleshooter.findings(m, 'browsing')
        self.assertTrue(found)
        for f in found:
            self.assertTrue(f.get('tech'), f['id'])
        self.assertIn('explanation_tech', troubleshooter.public({'explanation_tech': ['x']}))


class TestEndpoints(unittest.TestCase):
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

    def get(self, path):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers={'Host': f'127.0.0.1:{self.port}'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    def test_today_endpoint(self):
        with patch('today.get', return_value={'title': 'Your PC looks healthy', 'tiles': []}) as get:
            self.assertEqual(self.get('/api/today?refresh=1')['title'], 'Your PC looks healthy')
            get.assert_called_once_with(True, True)

    def test_check_returns_both_voices(self):
        with patch('system_checks.check', return_value=BATTERY):
            r = self.get('/api/check?name=battery')
        self.assertIn('original', r['summary'])
        self.assertTrue(r['technical'].startswith('Battery L22D4PA0'))


class TestAppWindow(unittest.TestCase):
    def test_edge_app_mode(self):
        with patch('pathlib.Path.exists', return_value=True), patch('subprocess.Popen') as popen:
            dashboard.open_app_window('http://127.0.0.1:8765')
        args = popen.call_args[0][0]
        self.assertTrue(args[0].endswith('msedge.exe'))
        self.assertIn('--app=http://127.0.0.1:8765', args)

    def test_falls_back_to_default_browser(self):
        with patch('pathlib.Path.exists', return_value=False), patch('webbrowser.open') as browser:
            dashboard.open_app_window('http://127.0.0.1:8765')
        browser.assert_called_once_with('http://127.0.0.1:8765')


if __name__ == '__main__':
    unittest.main()
