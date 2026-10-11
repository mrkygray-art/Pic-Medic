"""Guided troubleshooting: evidence, recommendations, validation and saved cases (fixtures; no measuring)."""
import os
import tempfile
import unittest
from unittest.mock import patch

import troubleshooter as t


def proc(name, cpu=0, ram_gb=0.1, io_mb=0, count=1):
    return {'name': name, 'cpu': cpu, 'ram_gb': ram_gb, 'io': io_mb * 1048576, 'io_mb_s': io_mb, 'count': count}


SLOW_PC = {
    'cpu': 35, 'memory': 91, 'disk_busy': 78, 'memory_total_gb': 8.0, 'samples': 5,
    'processes': [proc('chrome', cpu=12, ram_gb=3.1, io_mb=2, count=24), proc('OneDrive', io_mb=30), proc('MsMpEng', cpu=8, io_mb=25),
                  proc('Teams', ram_gb=0.9, io_mb=10), proc('svchost', ram_gb=1.0, io_mb=1)],
    'startup': [{'name': n, 'on': on} for n, on in [('Steam', True), ('Discord', True), ('Spotify', True), ('SecurityHealth', True),
                                                    ('OneDrive', True), ('RtkAudUService', True), ('EpicGamesLauncher', False)]],
    'reboot': {'UptimeDays': 12.0, 'ComponentServicing': False, 'WindowsUpdate': True},
    'disk': {'Disks': [{'Name': 'WDC WD10EZEX', 'MediaType': 'HDD'}], 'Volumes': [{'Drive': 'C:', 'SizeGB': 237, 'FreeGB': 9}]},
    'power': {'Plan': 'Power saver', 'OnBattery': True},
}
QUIET_PC = {'cpu': 8, 'memory': 50, 'disk_busy': 2, 'memory_total_gb': 16, 'samples': 5, 'processes': [proc('firefox', ram_gb=1.1)],
            'startup': [{'name': 'SecurityHealth', 'on': True}], 'reboot': {'UptimeDays': 1}, 'disk': {'Volumes': [{'Drive': 'C:', 'SizeGB': 475, 'FreeGB': 74}]}}


class TestEvidence(unittest.TestCase):
    def ids(self, m, context):
        return [f['id'] for f in t.findings(m, context)]

    def test_startup_context_leads_with_startup_apps_and_disk(self):
        found = t.findings(SLOW_PC, 'startup')
        self.assertEqual(found[0]['id'], 'startup')
        self.assertIn('usually are not needed right away (Steam, Discord, Spotify)', found[0]['text'])
        self.assertEqual(found[0]['target'], 'Steam')
        disk = next(f for f in found if f['id'] == 'disk')
        self.assertIn('The disk is busy 78% of the time; OneDrive, MsMpEng and Teams account for', disk['text'])

    def test_browsing_and_gaming_contexts(self):
        self.assertIn(self.ids(SLOW_PC, 'browsing')[0], ('browser', 'memory'))
        browser = next(f for f in t.findings(SLOW_PC, 'browsing') if f['id'] == 'browser')
        self.assertIn('Chrome is using 3.1 GB of memory across 24 processes', browser['text'])
        self.assertEqual(self.ids(SLOW_PC, 'gaming')[0], 'power')

    def test_restart_space_and_hard_drive_are_found(self):
        ids = self.ids(SLOW_PC, 'always')
        for expected in ('restart', 'space', 'hdd', 'memory', 'disk'):
            self.assertIn(expected, ids)

    def test_security_and_drivers_are_never_suggested_for_startup_removal(self):
        startup = next(f for f in t.findings(SLOW_PC, 'startup') if f['id'] == 'startup')
        self.assertNotIn('SecurityHealth', startup['text'])
        self.assertNotIn('RtkAudUService', startup['text'])

    def test_quiet_pc_has_no_findings(self):
        self.assertEqual(t.findings(QUIET_PC, 'always'), [])

    def test_background_windows_work_is_not_closed(self):
        m = dict(QUIET_PC, cpu=80, processes=[proc('MsMpEng', cpu=60), proc('firefox', cpu=5)])
        cpu = next(f for f in t.findings(m, 'always') if f['id'] == 'cpu')
        self.assertEqual(cpu['action'], 'background_task')
        self.assertIn('Microsoft Defender', t.action_plan(cpu)['title'])


class TestRouting(unittest.TestCase):
    def test_slowness_starts_a_case_with_context_when_known(self):
        from intent_engine import classify
        cases = {'My computer is slow': None, 'My laptop takes forever to boot': 'startup', 'Games lag a lot': 'gaming',
                 'Chrome is really slow': 'browsing'}
        for question, context in cases.items():
            with self.subTest(question=question):
                self.assertEqual((classify(question)['intent'], classify(question)['context']), ('slow', context))
        self.assertNotEqual(classify('My internet is slow')['intent'], 'slow')
        self.assertEqual(classify('My computer froze')['intent'], 'performance')


class TestCaseLifecycle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = patch('troubleshooter.CASES_FILE', os.path.join(self.dir, 'cases.json'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_understand_investigate_recommend_validate_save(self):
        case = t.start('My computer is slow')
        self.assertEqual((case['status'], case['question']['text']), ('asking', 'When does your computer feel slow?'))
        with patch('troubleshooter.measure', return_value=SLOW_PC):
            case = t.investigate(case['id'], 'startup')
        self.assertEqual(case['status'], 'recommended')
        self.assertEqual(case['recommendation']['action'], 'disable_startup')
        self.assertEqual(case['recommendation']['tool'], 'startup')
        self.assertTrue(case['recommendation']['steps'])
        after = dict(SLOW_PC, startup=[dict(a, on=False) if a['name'] == 'Steam' else a for a in SLOW_PC['startup']])
        with patch('troubleshooter.measure', return_value=after):
            case = t.validate(case['id'])
        self.assertIn('Steam is now turned off at startup. Startup apps turned on: 6 before, 5 now.', case['validation'])
        case = t.feedback(case['id'], 'better')
        self.assertEqual((case['status'], case['outcome']), ('resolved', 'Fixed: "Turn off Steam at startup" made the computer feel faster.'))
        self.assertEqual(t.history()[0]['status'], 'resolved')

    def test_not_fixed_moves_to_the_next_suggestion(self):
        case = t.start('slow')
        with patch('troubleshooter.measure', return_value=SLOW_PC):
            case = t.investigate(case['id'], 'startup')
            first = case['recommendation']['action']
            case = t.validate(case['id'])
        case = t.feedback(case['id'], 'same')
        self.assertEqual(case['status'], 'not_resolved')
        self.assertNotEqual(case['next']['action'], first)

    def test_nothing_found_suggests_measuring_while_slow(self):
        case = t.start('slow')
        with patch('troubleshooter.measure', return_value=QUIET_PC):
            case = t.investigate(case['id'], 'always')
        self.assertEqual(case['recommendation']['action'], 'performance_watch')
        self.assertEqual(case['explanation'], ['Nothing stands out right now.'])
        self.assertIn('Measured for', case['measured'])

    def test_restart_validation_needs_an_actual_restart(self):
        case = t.start('slow')
        with patch('troubleshooter.measure', return_value=SLOW_PC):
            case = t.investigate(case['id'], 'always')
        case = t.get(case['id'])
        case['recommendation'] = t.action_plan({'action': 'restart', 'id': 'restart'})
        case['after'] = SLOW_PC
        self.assertIn('does not see a restart yet', t.compare(case)[0])
        case['after'] = dict(SLOW_PC, reboot={'UptimeDays': 0.1})
        self.assertIn('has been restarted', t.compare(case)[0])

    def test_page_view_hides_raw_measurements(self):
        case = t.start('slow')
        with patch('troubleshooter.measure', return_value=SLOW_PC):
            case = t.investigate(case['id'], 'startup')
        self.assertNotIn('baseline', t.public(case))


if __name__ == '__main__':
    unittest.main()
