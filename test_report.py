"""Technician report: content, escaping and the endpoint. Fixtures only; the endpoint test patches the checks."""
import unittest
import urllib.request
from datetime import datetime
from unittest.mock import patch

import dashboard
import report
from test_bugfixes import LocalServer

OVERVIEW = {'available': True, 'manufacturer': 'LENOVO', 'product_name': 'LOQ 15IRH8', 'model': '82XV',
            'windows': {'Caption': 'Microsoft Windows 11 Home', 'BuildNumber': '26300'},
            'processor': {'Name': 'Intel Core i5-13420H', 'NumberOfCores': 8, 'NumberOfLogicalProcessors': 12},
            'ram_total_gb': 15.7, 'ram_modules': [{'size_gb': 8.0, 'speed_mts': 5600, 'part_number': 'M425R1GB4BB0-CWMOL'}],
            'graphics': ['NVIDIA GeForce RTX 2050'], 'drives': [{'model': 'Micron 512GB', 'size_gb': 512}], 'battery_part_numbers': ['L22D4PA0']}
CHECKS = {'battery': {'available': True, 'Present': True, 'ChargePercent': 90, 'DesignCapacity_mWh': 60000, 'FullChargeCapacity_mWh': 57000, 'HealthPercent': 95},
          'startup_apps': {'available': True, 'Count': 1, 'Apps': [{'Name': '<script>alert(1)</script>', 'Scope': 'This user'}]}}


class TestBuild(unittest.TestCase):
    def page(self, scan=None, turns=None):
        return report.build(OVERVIEW, scan, CHECKS, turns, generated=datetime(2026, 10, 10, 17, 0))

    def test_sections_and_print_button(self):
        page = self.page(turns=[{'q': 'How is my battery?', 'a': 'About 95% of new.'}])
        for text in ('PC Medic technician report', 'LENOVO LOQ 15IRH8 82XV', 'M425R1GB4BB0-CWMOL', 'about 95% of new',
                     'Q: How is my battery?', 'Technician notes', 'window.print()', 'No Health Check has been run'):
            self.assertIn(text, page)

    def test_untrusted_text_is_escaped(self):
        page = self.page(turns=[{'q': '<img src=x onerror=alert(1)>', 'a': 'ok'}])
        self.assertNotIn('<script>alert(1)', page)
        self.assertNotIn('<img src=x', page)
        self.assertIn('&lt;script&gt;', page)

    def test_health_check_findings(self):
        page = self.page(scan=dashboard.DEMO)
        self.assertIn('From the Health Check on 2026-10-09 17:00 UTC', page)
        self.assertIn('class="finding', page)

    def test_conversation_is_bounded(self):
        page = self.page(turns=[{'q': f'question {i}', 'a': 'x' * 10000} for i in range(60)])
        self.assertIn('question 39', page)
        self.assertNotIn('question 40', page)
        self.assertNotIn('x' * 4001, page)


class TestLayout(unittest.TestCase):
    def test_service_fields_are_printed_and_escaped(self):
        page = report.build(OVERVIEW, None, CHECKS, [], generated=datetime(2026, 10, 10, 17, 0),
                            service={'customer': 'Jane <b>Doe</b>', 'technician': 'Ky', 'ticket': 'T-1001'})
        for text in ('Customer', 'Jane &lt;b&gt;Doe&lt;/b&gt;', 'Ticket number', 'T-1001', 'Technician', 'Service date', '2026-10-10'):
            self.assertIn(text, page)
        self.assertNotIn('<b>Doe', page)

    def test_main_report_then_optional_appendix(self):
        page = report.build(OVERVIEW, None, CHECKS, [{'q': 'hi', 'a': 'there'}], generated=datetime(2026, 10, 10, 17, 0))
        main, appendix = page.split('<section class="appendix">')
        for text in ('At a glance', 'Recommended next steps', 'Technician notes', 'Technician signature', 'Read-only diagnostics'):
            self.assertIn(text, main)
        for text in ('Appendix: technical details', 'Q: hi', 'about 95% of new'):
            self.assertIn(text, appendix)
        self.assertIn('no-appendix', page)  # the print toggle

    def test_battery_is_measured_not_forecast(self):
        rows = {r[0]: r for r in report.glance(CHECKS)}
        self.assertIn('Measured capacity 95% of original', rows['Battery'][2])

    def test_network_row_gives_context(self):
        ports = {'available': True, 'Tcp': [{'Port': 445, 'Scope': 'all', 'Process': 'System'}, {'Port': 5000, 'Scope': 'loopback'}],
                 'Firewall': [{'Profile': 'Public', 'Enabled': True, 'DefaultInbound': 'NotConfigured'}], 'NetworkTypes': ['Private']}
        area, state, text = report.glance({'listening_ports': ports})[0]
        self.assertIn('1 TCP ports listen on a network interface', text)
        self.assertIn('Firewall on', text)
        self.assertIn('not the same as exposed', text)


class TestEventDates(unittest.TestCase):
    def test_powershell_dates_become_iso(self):
        from event_log_analyzer import event_time
        self.assertEqual(event_time('/Date(1791631615000)/'), '2026-10-10T11:26:55+00:00')
        self.assertEqual(event_time('2026-10-09T12:00:00'), '2026-10-09T12:00:00')


class TestEndpoint(LocalServer):
    def test_returns_html_page(self):
        with patch('report.generate', return_value='<!doctype html><title>r</title>') as gen:
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/technician-report', data=b'{"conversation":[{"q":"hi","a":"yo"}]}',
                                         headers={'Content-Type': 'application/json', 'X-PC-Medic-Token': dashboard.TOKEN}, method='POST')
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(r.headers['Content-Type'], 'text/html; charset=utf-8')
                self.assertIn(b'<title>r</title>', r.read())
        scan, turns = gen.call_args.args
        self.assertEqual(turns, [{'q': 'hi', 'a': 'yo'}])
        self.assertIsNotNone(scan)  # demo server supplies the demo scan

    def test_rejects_bad_conversation(self):
        self.assertEqual(self.call('/api/technician-report', {'conversation': 'nope'})[0], 400)


if __name__ == '__main__':
    unittest.main()
