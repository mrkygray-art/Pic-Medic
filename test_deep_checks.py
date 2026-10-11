"""Deep checks: security posture, blue-screen analysis and the administrator deep scan.
Run: python -m unittest discover -p "test_*.py"
"""
import json
import os
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import bluescreen
import dashboard
import deep_scan
import intent_engine
import system_checks

K = 0xFFFFF80000000000


def fake_minidump(code=0xD1, params=(0, 2, 0, 0), drivers=(), stack=(), entry=0x90):
    """A small 64-bit triage dump laid out the way bluescreen.parse_dump reads it."""
    b = bytearray(0x4000)
    b[0:8] = b'PAGEDU64'
    struct.pack_into('<I', b, 0x0C, 26100)
    struct.pack_into('<I', b, 0x38, code)
    for i, p in enumerate(params):
        struct.pack_into('<Q', b, 0x40 + 8 * i, p)
    struct.pack_into('<I', b, 0xF98, 4)
    tri, drv_off, pool, stack_off = 0x2000, 0x2100, 0x3000, 0x3800
    struct.pack_into('<IIII', b, tri + 40, stack_off, 8 * len(stack), drv_off, len(drivers))
    pos = pool
    for i, (name, base, size) in enumerate(drivers):
        e = drv_off + i * entry
        struct.pack_into('<I', b, e, pos)
        struct.pack_into('<Q', b, e + 8 + 0x30, base)
        struct.pack_into('<I', b, e + 8 + 0x40, size)
        text = name.encode('utf-16-le')
        struct.pack_into('<I', b, pos, len(name))
        b[pos + 4:pos + 4 + len(text)] = text
        pos += 4 + len(text) + 2
    for i, v in enumerate(stack):
        struct.pack_into('<Q', b, stack_off + 8 * i, v)
    return bytes(b)


DRIVERS = [('ntoskrnl.exe', K, 0x1000000), ('hal.dll', K + 0x2000000, 0x100000), ('nvlddmkm.sys', K + 0x5000000, 0x3000000), ('tcpip.sys', K + 0x9000000, 0x300000)]


class TestBlueScreens(unittest.TestCase):
    def test_event_message(self):
        msg = ('The computer has rebooted from a bugcheck.  The bugcheck was: 0x0000009f (0x0000000000000003, 0xffffd30b1c2e5060, 0xfffff80512a7f750, 0xffffd30b2a1f3010). '
               'A dump was saved in: C:\\WINDOWS\\Minidump\\101026-11250-01.dmp. Report Id: 1234.')
        ev = bluescreen.parse_event(msg)
        self.assertEqual((ev['code'], ev['dump'], len(ev['params'])), (0x9F, '101026-11250-01.dmp', 4))
        self.assertIsNone(bluescreen.parse_event('something else'))

    def test_explain(self):
        self.assertEqual(bluescreen.explain(0x116)['name'], 'VIDEO_TDR_FAILURE')
        self.assertIn('graphics', bluescreen.explain(0x116)['advice'])
        self.assertEqual(bluescreen.explain(0x12345)['name'], 'Unknown stop code')

    def test_dump_parameter_points_into_driver(self):
        d = bluescreen.parse_dump(fake_minidump(0xD1, (0, 2, 0, K + 0x9000100), DRIVERS))
        self.assertEqual((d['code'], d['driver'], d['build']), (0xD1, 'tcpip.sys', 26100))
        self.assertIn('parameter', d['reason'])

    def test_dump_first_non_kernel_driver_on_stack(self):
        stack = (K + 0x500, K + 0x2000100, K + 0x5000100, K + 0x9000100)
        d = bluescreen.parse_dump(fake_minidump(0x116, (0, 0, 0, 0), DRIVERS, stack, entry=0xA0))
        self.assertEqual(d['driver'], 'nvlddmkm.sys')
        self.assertIn('stack', d['reason'])

    def test_dump_never_guesses_from_bad_data(self):
        self.assertIsNone(bluescreen.parse_dump(b'MDMP' + bytes(0x3000)))  # a user-mode dump
        junk = bytearray(fake_minidump(0x50)); junk[0x2100:0x2400] = os.urandom(0x300)
        struct.pack_into('<I', junk, 0x2000 + 52, 40)
        d = bluescreen.parse_dump(bytes(junk))
        self.assertEqual((d['code'], d['driver']), (0x50, None))
        only_kernel = bluescreen.parse_dump(fake_minidump(0x1A, (0, 0, 0, 0), DRIVERS[:2], (K + 0x10,)))
        self.assertIsNone(only_kernel['driver'])

    def test_crash_check_uses_deep_scan_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'deep_scan.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'finished': '2026-10-11T10:00:00+00:00', 'Dumps': [{'file': '101026-11250-01.dmp', 'driver': 'nvlddmkm.sys', 'reason': 'stack', 'company': 'NVIDIA Corporation', 'version': '32.0.15.6094'}]}, f)
            data = {'available': True, 'UnexpectedRestarts': [], 'BlueScreens': [{'Date': '2026-10-10T09:00:00', 'Code': '0x0000009f',
                    'Text': 'The bugcheck was: 0x0000009f (0x3, 0x0, 0x0, 0x0). A dump was saved in: C:\\WINDOWS\\Minidump\\101026-11250-01.dmp.'}]}
            with patch.object(system_checks, 'DEEP_SCAN_FILE', path):
                system_checks.crash_extras(data)
        b = data['BlueScreens'][0]
        self.assertEqual((b['name'], b['Driver']['driver']), ('DRIVER_POWER_STATE_FAILURE', 'nvlddmkm.sys'))
        text = system_checks.describe('crashes', data)
        self.assertIn('Likely cause: nvlddmkm.sys from NVIDIA Corporation', text)
        cloud = system_checks.for_cloud('crashes', data)
        self.assertNotIn('Dump', cloud['BlueScreens'][0])
        self.assertTrue(system_checks.items('crashes', data))


BASE = {'available': True, 'Defender': {'RealTime': True, 'Antivirus': True, 'Mode': 'Normal', 'SignatureAgeDays': 0, 'QuickScanAgeDays': 1, 'Tamper': True},
        'Antivirus': [{'Name': 'Windows Defender', 'State': 397568}], 'Firewall': [{'Profile': p, 'Enabled': True} for p in ('Domain', 'Private', 'Public')],
        'UacOn': 1, 'UacPrompt': 5, 'UacSecureDesktop': 1, 'SecureBoot': 1, 'UserIsAdmin': False, 'LocalAdminCount': 1, 'LicenseStatus': 1,
        'Build': 26100, 'UBR': 1, 'DisplayVersion': '24H2', 'Edition': 'Professional', 'LastPatch': {'Id': 'KB1', 'Date': '2026-06-01T00:00:00'},
        'BitLocker': 1, 'Tpm': {'TPM Present': 'True', 'TPM Version': '2.0'}, 'RemoteDesktopOn': False, 'SMB1': None}


def states(d, today=date(2026, 6, 10)):
    return {i['area']: i['state'] for i in system_checks.security_items(d, today)}


class TestSecurity(unittest.TestCase):
    def test_protected_pc(self):
        self.assertEqual(set(states(BASE).values()), {'good'})
        recent = {**BASE, 'LastPatch': {'Date': date.today().isoformat()}, 'DisplayVersion': '25H2'}
        self.assertIn('Everything PC Medic checked looks protected', system_checks.describe('security', recent))

    def test_problems(self):
        d = {**BASE, 'Defender': {'RealTime': False, 'Antivirus': False}, 'Antivirus': [], 'Firewall': [{'Profile': 'Public', 'Enabled': False}, {'Profile': 'Private', 'Enabled': True}],
             'UacOn': 0, 'SecureBoot': 0, 'BitLocker': 2, 'UserIsAdmin': True, 'SMB1': 1, 'RemoteDesktopOn': True}
        s = states(d)
        self.assertEqual((s['Antivirus'], s['Firewall'], s['User Account Control'], s['Secure Boot'], s['SMB1']), ('problem', 'attention', 'problem', 'attention', 'attention'))
        self.assertEqual((s['Drive encryption'], s['Accounts'], s['Remote Desktop']), ('note', 'note', 'note'))

    def test_third_party_antivirus_counts(self):
        d = {**BASE, 'Defender': {'RealTime': False, 'Antivirus': False, 'Mode': 'Passive Mode'}, 'Antivirus': [{'Name': 'Windows Defender', 'State': 393472}, {'Name': 'Bitdefender', 'State': 266240}]}
        self.assertEqual(states(d)['Antivirus'], 'good')

    def test_windows_support_end(self):
        self.assertEqual(states(BASE, date(2026, 9, 1))['Windows support'], 'attention')   # 24H2 Home/Pro ends 2026-10-13
        self.assertEqual(states(BASE, date(2026, 11, 1))['Windows support'], 'problem')
        self.assertEqual(states({**BASE, 'Edition': 'Enterprise'}, date(2026, 11, 1))['Windows support'], 'note')
        self.assertEqual(states({**BASE, 'DisplayVersion': '26H2'})['Windows support'], 'note')

    def test_cloud_copy_has_no_patch_id(self):
        cloud = system_checks.for_cloud('security', dict(BASE))
        self.assertNotIn('LastPatch', cloud)
        self.assertTrue(cloud['Items'])

    def test_routing(self):
        for q in ('Is my computer secure?', 'is Defender on', 'how secure is my laptop', 'check my firewall'):
            self.assertEqual(intent_engine.classify(q, {}).get('check'), 'security', q)
        self.assertNotEqual(intent_engine.classify('I installed security cameras', {}).get('check'), 'security')


SCAN = {'finished': '2026-10-11T10:00:00+00:00', 'sfc': False,
        'Disks': [{'Name': 'Micron 512', 'MediaType': 'SSD', 'BusType': 'NVMe', 'Health': 'Healthy', 'WearPercent': 3, 'TemperatureC': 38, 'PowerOnHours': 1200, 'ReadErrorsUncorrected': 0, 'WriteErrorsUncorrected': 0}],
        'Boots': [{'BootMs': 42000, 'MainPathMs': 20000, 'PostBootMs': 22000}, {'BootMs': 50000}],
        'SlowStartup': [{'Kind': 'App', 'Name': 'SecretVendorUpdater', 'DelayMs': 9000, 'TotalMs': 12000}],
        'Dirty': [{'Drive': 'C:', 'Dirty': False, 'Text': 'Volume - C: is NOT Dirty'}],
        'Dism': {'state': 'repairable', 'text': 'The component store is repairable.'},
        'BitLocker': [{'Drive': 'C:', 'Protection': 'On', 'Protectors': ['Tpm', 'RecoveryPassword']}],
        'Tpm': {'Present': True, 'Ready': True}, 'Dumps': [], 'LiveKernelReports': [{'Kind': 'WATCHDOG'}]}


class TestDeepScan(unittest.TestCase):
    def test_items_and_summary(self):
        rows = {r['area']: r for r in deep_scan.items(SCAN)}
        self.assertEqual(rows['Windows image']['state'], 'attention')
        self.assertIn('SecretVendorUpdater', rows['Startup time']['plain'])
        self.assertEqual(rows['BitLocker']['state'], 'good')
        self.assertEqual(rows['Hidden hangs']['state'], 'note')
        self.assertIn('1 thing needs attention', deep_scan.describe(SCAN))

    def test_dirty_bit_only_trusts_fsutil_output(self):
        rows = {r['area'] for r in deep_scan.items({**SCAN, 'Dirty': [{'Drive': 'C:', 'Dirty': False, 'Text': 'Error: Access is denied.'}]})}
        self.assertNotIn('File system', rows)

    def test_cloud_copy_drops_app_names(self):
        self.assertNotIn('SecretVendorUpdater', json.dumps(deep_scan.for_cloud(SCAN)))

    def test_output_path_is_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(deep_scan.safe_output(os.path.join(tmp, 'deep_scan.json')).name, 'deep_scan.json')
            with self.assertRaises(SystemExit):
                deep_scan.safe_output(os.path.join(tmp, 'evil.dll'))
            with self.assertRaises(SystemExit):
                deep_scan.safe_output(os.path.join(tmp, 'missing', 'deep_scan.json'))

    def test_main_writes_result_or_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'deep_scan.json')
            with patch('deep_scan.run', return_value=dict(SCAN)):
                deep_scan.main(['--output', out])
            self.assertEqual(json.load(open(out, encoding='utf-8'))['finished'], SCAN['finished'])
            with patch('deep_scan.run', side_effect=RuntimeError('x')):
                deep_scan.main(['--output', out])
            self.assertIn('stopped', json.load(open(out, encoding='utf-8'))['error'])


class TestDeepScanServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        cls.server.demo = False
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        dashboard.ACTIVITY.update(kind=None, owner=None, until=0.0)
        dashboard.DEEP.update(state='idle', error=None)

    def call(self, path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST',
                                     headers={'Content-Type': 'application/json', 'X-PC-Medic-Token': dashboard.TOKEN, 'Host': f'127.0.0.1:{self.port}'})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    def wait_done(self):
        for _ in range(100):
            if dashboard.DEEP['state'] not in ('asking', 'running'):
                return
            threading.Event().wait(0.05)

    def test_declined_prompt_releases_the_slot(self):
        with patch('dashboard.run_elevated', side_effect=PermissionError('You chose No')):
            status, r = self.call('/api/deep-scan', {'owner': 'window-deep-1'})
            self.assertEqual(status, 200)
            self.wait_done()
        self.assertEqual(self.call('/api/deep-scan')[1]['state'], 'declined')
        self.assertIsNone(dashboard.ACTIVITY['owner'])

    def test_finished_scan_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'deep_scan.json')
            def fake_wait(_):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(SCAN, f)
            with patch('dashboard.DEEP_FILE', path), patch.object(system_checks, 'DEEP_SCAN_FILE', path), \
                 patch('dashboard.run_elevated', return_value=1) as elevate, patch('dashboard.wait_process', side_effect=fake_wait):
                self.call('/api/deep-scan', {'owner': 'window-deep-2', 'sfc': True})
                self.wait_done()
                r = self.call('/api/deep-scan')[1]
            self.assertIn('--sfc', elevate.call_args[0][0])
            self.assertEqual(elevate.call_args[0][0][2], path)
        self.assertEqual(r['state'], 'done')
        self.assertTrue(any(i['area'] == 'Windows image' for i in r['items']))

    def test_one_diagnostic_at_a_time(self):
        dashboard.activity_conflict('someone-else-1', 'health')
        status, r = self.call('/api/deep-scan', {'owner': 'window-deep-3'})
        self.assertEqual(status, 409)

    def test_demo_mode_refuses(self):
        self.server.demo = True
        try:
            self.assertEqual(self.call('/api/deep-scan', {'owner': 'window-deep-4'})[0], 400)
        finally:
            self.server.demo = False


if __name__ == '__main__':
    unittest.main()


class TestErrorCodes(unittest.TestCase):
    def test_lookup(self):
        import error_codes
        self.assertEqual(error_codes.lookup('0x8024200b')['name'], 'WU_E_UH_INSTALLERFAILURE')
        self.assertEqual(error_codes.lookup('error 80070643 again')['code'], '0x80070643')
        self.assertEqual(error_codes.lookup('0x0000009F')['name'], 'DRIVER_POWER_STATE_FAILURE')
        self.assertEqual(error_codes.lookup('0xC0000005')['name'], 'STATUS_ACCESS_VIOLATION')
        self.assertEqual(error_codes.lookup('0x8024202A')['source'], 'the code’s error family')
        self.assertIsNone(error_codes.lookup('no code here'))

    def test_routing_and_update_check(self):
        self.assertEqual(intent_engine.classify('what does error 0x800F0823 mean', {}), {'intent': 'error_code', 'code': '0x800F0823', 'scan': 'none'})
        self.assertEqual(intent_engine.classify('windows update error 8024200B', {})['code'], '0x8024200B')
        d = {'available': True, 'SuccessCount': 5, 'FailureCount': 3, 'Failures': [
            {'Date': '2026-10-04T10:00:00', 'Error': '0x8024200B', 'Update': 'Lenovo Driver Update'},
            {'Date': '2026-10-03T10:00:00', 'Error': '0x8024200B', 'Update': 'Lenovo Driver Update'},
            {'Date': '2026-10-02T10:00:00', 'Error': '0x80073D02', 'Update': '9NBLGGH4NNS1-Microsoft.Photos'}]}
        text = system_checks.describe('updates', d)
        self.assertIn('Error 0x8024200B, 2 times', text)
        self.assertIn('driver and firmware updates', text)
        rows = system_checks.items('updates', d)
        self.assertEqual([r['state'] for r in rows], ['attention', 'note'])
        self.assertIn('WU_E_UH_INSTALLERFAILURE', system_checks.describe_technical('updates', d))

    def test_error_code_endpoint(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler); server.demo = True
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{port}/api/error-code?code=0x80070070', headers={'Host': f'127.0.0.1:{port}'})
            with urllib.request.urlopen(req, timeout=5) as r:
                body = json.load(r)
            self.assertEqual(body['name'], 'ERROR_DISK_FULL')
            self.assertIn('What to do', body['summary'])
        finally:
            server.shutdown(); server.server_close()
