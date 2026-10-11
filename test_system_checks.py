"""Read-only system checks: summaries, cloud sanitizing and routing. Uses fixtures, so it runs anywhere."""
import json
import unittest
from unittest.mock import patch

import system_checks as sc
from intent_engine import classify


class TestSummaries(unittest.TestCase):
    def battery(self, full):
        return {'available': True, 'Present': True, 'Model': 'L22D4PA0', 'ChargePercent': 80, 'OnAC': False,
                'DesignCapacity_mWh': 60000, 'FullChargeCapacity_mWh': full, 'CycleCount': 300, 'HealthPercent': round(100 * full / 60000)}

    def test_battery_wear_levels(self):
        self.assertIn('That is healthy', sc.describe('battery', self.battery(57000)))
        self.assertIn('noticeable wear', sc.describe('battery', self.battery(42000)))
        self.assertIn('heavy wear', sc.describe('battery', self.battery(30000)))
        self.assertIn('no battery detected', sc.describe('battery', {'available': True, 'Present': False}))

    def test_crashes_and_updates(self):
        crashes = sc.describe('crashes', {'available': True, 'BlueScreens': [{'Date': '2026-10-01T10:00:00', 'Code': '0x000000d1'}], 'UnexpectedRestarts': [], 'DirtyShutdowns': 0})
        self.assertIn('Blue screens: 1. Stop codes: 0x000000d1.', crashes)
        updates = sc.describe('updates', {'available': True, 'SuccessCount': 3, 'FailureCount': 1, 'Failures': [{'Date': '2026-10-10T01:00:00', 'Error': '0x80073D02', 'Update': '9NTXGKQ8P7N0-MicrosoftWindows.CrossDevice'}]})
        self.assertIn('Microsoft Store app MicrosoftWindows.CrossDevice', updates)
        self.assertIn('Store app was open', updates)

    def test_ports_dedupe_and_dynamic_range(self):
        data = {'available': True, 'UdpCount': 2, 'Tcp': [{'Port': 135, 'LocalOnly': False, 'Process': 'svchost'}, {'Port': 135, 'LocalOnly': False, 'Process': 'svchost'},
                                                          {'Port': 49664, 'LocalOnly': False, 'Process': 'lsass'}, {'Port': 5939, 'LocalOnly': True, 'Process': 'x'}]}
        text = sc.describe('listening_ports', data)
        self.assertIn('3 TCP ports are listening; 2 accept connections from the network', text)
        self.assertEqual(text.count('Port 135'), 1)
        self.assertIn('Plus 1 high-numbered ports', text)

    def test_unavailable(self):
        self.assertIn('unavailable', sc.describe('disk_health', {'available': False, 'reason': 'The check timed out.'}))


class TestCloudPrivacy(unittest.TestCase):
    def test_no_process_or_app_names_or_battery_model(self):
        ports = sc.for_cloud('listening_ports', {'available': True, 'Tcp': [{'Port': 3389, 'LocalOnly': False, 'Process': 'svchost'}, {'Port': 3389, 'LocalOnly': False, 'Process': 'svchost'}]})
        self.assertEqual(ports['Tcp'], [{'Port': 3389, 'LocalOnly': False, 'Service': 'Remote Desktop'}])
        apps = sc.for_cloud('startup_apps', {'available': True, 'Count': 2, 'Apps': [{'Name': 'SecretTool', 'Scope': 'This user'}, {'Name': 'Teams', 'Scope': 'All users'}]})
        self.assertNotIn('SecretTool', json.dumps(apps))
        self.assertEqual((apps['AllUsers'], apps['ThisUser']), (1, 1))
        self.assertNotIn('Model', sc.for_cloud('battery', {'available': True, 'Present': True, 'Model': 'L22D4PA0'}))


class TestRouting(unittest.TestCase):
    def test_questions_reach_the_right_check(self):
        cases = {'How is my battery health?': 'battery', 'My battery drains fast': 'battery', 'I got a blue screen': 'crashes',
                 'My PC restarts by itself': 'crashes', 'Windows update keeps failing': 'updates', 'What startup apps do I have?': 'startup_apps',
                 'Do I need to restart?': 'pending_reboot', 'Is my SSD failing?': 'disk_health', 'My hard drive is full': 'disk_health'}
        for question, check in cases.items():
            with self.subTest(question=question):
                self.assertEqual(classify(question).get('check'), check)

    def test_existing_routes_unchanged(self):
        self.assertEqual(classify('I need a replacement battery')['intent'], 'replacement_part')
        self.assertEqual(classify('My laptop is not charging')['intent'], 'guided_knowledge')
        self.assertEqual(classify('Can I upgrade my SSD?')['intent'], 'storage_upgrade')


if __name__ == '__main__':
    unittest.main()
