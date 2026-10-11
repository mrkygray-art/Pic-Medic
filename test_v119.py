"""Battery report extras, the "What changed?" timeline, and greyed-out buttons that say why (no PowerShell, no network)."""
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import system_checks
import timeline
import today

BATTERY = {'available': True, 'Present': True, 'Model': 'L22D4PA0', 'ChargePercent': 99, 'OnAC': True, 'DesignCapacity_mWh': 60000,
           'FullChargeCapacity_mWh': 56800, 'CycleCount': 26, 'HealthPercent': 95, 'RuntimeFull': 'PT1H29M23S', 'RuntimeDesign': 'PT1H34M25S',
           'History': [{'Date': '2024-01-29', 'Full_mWh': 61190}, {'Date': '2025-06-23', 'Full_mWh': 57600}, {'Date': '2026-10-10', 'Full_mWh': 56800}]}


def battery(**over):
    d = json.loads(json.dumps({**BATTERY, **over}))
    system_checks.battery_extras(d)
    return d


class TestBatteryReport(unittest.TestCase):
    def test_iso_durations(self):
        self.assertEqual(system_checks.iso_minutes('PT1H29M23S'), 89)
        self.assertEqual(system_checks.iso_minutes('P1DT2H'), 1560)
        for empty in ('PT0S', '', None, 'garbage'):
            self.assertIsNone(system_checks.iso_minutes(empty))
        self.assertEqual((system_checks.hours_text(89), system_checks.hours_text(45)), ('1 h 29 min', '45 min'))

    def test_runtime_and_trend(self):
        d = battery()
        self.assertEqual((d['RuntimeFullMinutes'], d['RuntimeDesignMinutes']), (89, 94))
        self.assertEqual(d['History'][0], {'date': '2024-01-29', 'percent': 100})  # above design capacity is shown as 100%
        self.assertEqual({k: d['Trend'][k] for k in ('since', 'from', 'to', 'months')}, {'since': '2024-01-29', 'from': 100, 'to': 95, 'months': 32})
        text = system_checks.describe('battery', d)
        self.assertIn('lasts about 1 h 29 min of active use (about 1 h 34 min when it was new)', text)
        self.assertIn('Since January 2024 it went from 100% to 95% of new over 2 years and 8 months.', text)
        self.assertIn('stays above 80%', text)
        self.assertNotIn('about about', text)
        self.assertIn('runtime 1 h 29 min full', system_checks.describe_technical('battery', d))

    def test_projection_when_wearing_fast(self):
        d = battery(HealthPercent=86, History=[{'Date': '2025-10-01', 'Full_mWh': 60000}, {'Date': '2026-10-01', 'Full_mWh': 51600}])
        self.assertEqual(d['Trend']['months_to_80'], 5)
        self.assertIn('reaches 80%, where most people start to notice shorter battery life, in about 5 months.', system_checks.describe('battery', d))

    def test_short_history_has_no_trend_and_missing_runtime_is_left_out(self):
        d = battery(RuntimeFull='PT0S', History=[{'Date': '2026-09-01', 'Full_mWh': 57000}, {'Date': '2026-10-01', 'Full_mWh': 56800}])
        self.assertIsNone(d['Trend'])
        text = system_checks.describe('battery', d)
        self.assertNotIn('full charge it lasts', text)
        self.assertNotIn('Since', text)

    def test_cloud_view_has_no_battery_id(self):
        self.assertNotIn('L22D4PA0', json.dumps(system_checks.for_cloud('battery', battery())))

    def test_today_tile_shows_runtime(self):
        self.assertIn('About 1 h 29 min of use on a full charge.', today.battery_tile(battery())['plain'])

    def test_script_reads_runtime_and_history_without_serials(self):
        self.assertIn('RuntimeEstimates', system_checks.BATTERY)
        self.assertIn('BatteryChanged', system_checks.BATTERY)
        self.assertNotIn('SerialNumber', system_checks.BATTERY)


def snap(day, **over):
    base = {'date': day, 'at': day + 'T09:00:00', 'volumes': {'C:': {'free_gb': 78.0, 'size_gb': 475.0}}, 'battery': {'health': 95, 'runtime_min': 89},
            'crashes': [], 'blue_screens': [], 'last_update': '2026-10-01T03:00:00', 'restart_pending': False, 'startup': ['SecurityHealth', 'Steam']}
    return {**base, **over}


class TestTimeline(unittest.TestCase):
    def setUp(self):
        p = patch('timeline.DATA_FILE', os.path.join(tempfile.mkdtemp(), 'timeline.json'))
        p.start()
        self.addCleanup(p.stop)

    def test_snapshot_from_today_checks(self):
        r = {'disk_health': {'available': True, 'Volumes': [{'Drive': 'C:', 'SizeGB': 474.7, 'FreeGB': 78.3}]},
             'battery': battery(), 'crashes': {'available': True, 'BlueScreens': [{'Date': '2026-10-09T10:00:00', 'Code': '0x0000009f'}],
                                               'UnexpectedRestarts': ['2026-09-17T13:05:36']},
             'updates': {'available': True, 'LastSuccess': '2026-10-10T22:34:24'}, 'pending_reboot': {'available': True, 'WindowsUpdate': True},
             'startup_apps': {'available': True, 'Apps': [{'Name': 'Steam'}, {'Name': 'Discord'}]}}
        s = timeline.snapshot(r, datetime(2026, 10, 11, 9, 30))
        self.assertEqual(s['date'], '2026-10-11')
        self.assertEqual(s['volumes'], {'C:': {'free_gb': 78.3, 'size_gb': 474.7}})
        self.assertEqual(s['battery'], {'health': 95, 'runtime_min': 89})
        self.assertEqual(s['crashes'], ['2026-09-17T13:05:36', '2026-10-09T10:00:00'])
        self.assertEqual((s['blue_screens'], s['last_update'], s['restart_pending'], s['startup']),
                         (['2026-10-09T10:00:00'], '2026-10-10T22:34:24', True, ['Discord', 'Steam']))

    def test_unavailable_checks_are_left_out(self):
        self.assertEqual(set(timeline.snapshot({k: {'available': False} for k in ('disk_health', 'battery', 'crashes')})), {'date', 'at'})

    def test_one_snapshot_per_day_and_old_ones_dropped(self):
        timeline.record(snap('2026-06-01'))
        timeline.record(snap('2026-10-10'))
        timeline.record(snap('2026-10-11', battery={'health': 94}))
        timeline.record(snap('2026-10-11', battery={'health': 93}))
        entries = timeline.read()
        self.assertEqual([e['date'] for e in entries], ['2026-10-10', '2026-10-11'])
        self.assertEqual(entries[-1]['battery']['health'], 93)

    def test_what_changed(self):
        old = snap('2026-10-04', crashes=['2026-09-17T13:05:36'])
        new = snap('2026-10-11', volumes={'C:': {'free_gb': 58.0, 'size_gb': 475.0}}, battery={'health': 93},
                   crashes=['2026-09-17T13:05:36', '2026-10-09T10:00:00'], blue_screens=['2026-10-09T10:00:00'],
                   last_update='2026-10-08T03:00:00', restart_pending=True, startup=['Discord', 'SecurityHealth', 'Steam', 'Zoom'])
        items = timeline.compare(old, new)
        plain = {i['kind']: i['plain'] for i in items}
        self.assertEqual(items[0]['kind'], 'crashes')
        self.assertEqual(plain['crashes'], 'It had a blue-screen crash on Oct 9, the first in 21 days. It came after Windows installed updates on Oct 8.')
        self.assertEqual(plain['storage'], 'Drive C: has 20 GB less free space than on Oct 4 (58 GB free now).')
        self.assertEqual(plain['battery'], 'Battery health went from 95% to 93% of new since Oct 4.')
        self.assertEqual(plain['startup'], '2 new apps start with Windows since Oct 4: Discord, Zoom.')
        self.assertEqual(plain['updates'], 'Windows installed updates since Oct 4 (the latest on Oct 8).')
        self.assertEqual(plain['restart'], 'A restart is now needed to finish installing updates.')
        self.assertIn('C: free 78.0 → 58.0 GB', {i['kind']: i['tech'] for i in items}['storage'])

    def test_small_changes_are_ignored(self):
        self.assertEqual(timeline.compare(snap('2026-10-04'), snap('2026-10-11', volumes={'C:': {'free_gb': 77.0, 'size_gb': 475.0}})), [])

    def test_crash_already_known_is_not_new(self):
        self.assertEqual(timeline.compare(snap('2026-10-10', crashes=['2026-09-17T13:05:36']), snap('2026-10-11', crashes=['2026-09-17T13:05:36'])), [])

    def test_summary_uses_about_a_week_ago(self):
        entries = [snap('2026-09-20', startup=['A']), snap('2026-10-02', startup=['B']), snap('2026-10-05', startup=['C']), snap('2026-10-11', startup=['C', 'D'])]
        s = timeline.summary(entries)
        self.assertEqual((s['tracking_since'], s['since']), ('2026-09-20', '2026-10-05'))
        self.assertEqual(s['items'][0]['plain'], '1 new app starts with Windows since Oct 5: D.')
        self.assertEqual(timeline.summary([snap('2026-08-01'), snap('2026-10-11')])['since'], '2026-08-01')  # nothing within a week: the latest earlier one

    def test_first_day_has_nothing_to_compare(self):
        self.assertEqual(timeline.summary([snap('2026-10-11')]), {'tracking_since': '2026-10-11', 'since': None, 'items': []})
        self.assertEqual(timeline.summary([]), {'tracking_since': None, 'since': None, 'items': []})

    def test_day_by_day_newest_first(self):
        entries = [snap('2026-10-09'), snap('2026-10-10', startup=['SecurityHealth', 'Steam', 'Zoom']), snap('2026-10-11', startup=['SecurityHealth', 'Steam', 'Zoom'])]
        t = timeline.days(entries)
        self.assertEqual((t['snapshots'], t['tracking_since']), (3, '2026-10-09'))
        self.assertEqual([d['date'] for d in t['days']], ['2026-10-10'])  # a day with no changes is skipped

    def test_today_records_a_snapshot_but_not_in_demo(self):
        checks = {'battery': battery(), 'disk_health': {'available': True, 'Volumes': [{'Drive': 'C:', 'SizeGB': 475, 'FreeGB': 78}]},
                  'crashes': {'available': True}, 'updates': {'available': True}, 'pending_reboot': {'available': True}, 'startup_apps': {'available': True, 'Apps': []}}
        with patch('system_checks.check', side_effect=lambda n: checks[n]), patch('today.quick_performance', return_value=None):
            today.build(demo=True)
            self.assertEqual(timeline.read(), [])
            data = today.build()
        self.assertEqual(len(timeline.read()), 1)
        self.assertIsNone(data['changes']['since'])


class TestPage(unittest.TestCase):
    page = Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')

    def test_every_explained_button_exists(self):
        block = self.page.split('const WHY={')[1].split('};')[0]
        for key in re.findall(r"'([a-z-]+)':", block):
            with self.subTest(button=key):
                self.assertIn(f'id="{key}"', self.page)

    def test_new_screens_are_wired(self):
        for needle in ('id="today-changes"', "getJSON('/api/timeline')", "askAbout('How is my battery?')", 'explainDisabled()'):
            self.assertIn(needle, self.page)


if __name__ == '__main__':
    unittest.main()
