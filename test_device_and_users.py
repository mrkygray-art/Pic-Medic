"""Computer-type detection, custom-build identity, and one-account-only access."""
import json
import os
import socket
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from unittest.mock import patch

import dashboard
import local_security
import parts_research
import report
from hardware_advisor import identify
from test_bugfixes import LocalServer


class TestIdentify(unittest.TestCase):
    def kind(self, **fields):
        return identify(dict({'Manufacturer': 'Dell Inc.', 'Model': 'OptiPlex 7090'}, **fields))

    def test_device_types(self):
        self.assertEqual(self.kind(ChassisTypes=[10], PCSystemType=2)['DeviceType'], 'laptop')
        self.assertEqual(self.kind(ChassisTypes=[31], PCSystemType=2)['DeviceType'], 'laptop')  # convertible
        self.assertEqual(self.kind(ChassisTypes=[3], PCSystemType=1)['DeviceType'], 'desktop')
        self.assertEqual(self.kind(ChassisTypes=35, PCSystemType=1)['DeviceType'], 'desktop')  # single value, mini PC
        self.assertEqual(self.kind(ChassisTypes=[13], PCSystemType=1)['DeviceType'], 'all-in-one')
        self.assertEqual(self.kind(Manufacturer='Microsoft Corporation', Model='Virtual Machine', ChassisTypes=[3])['DeviceType'], 'virtual')
        self.assertEqual(self.kind(ChassisTypes=[2], BatteryModels=['X'])['DeviceType'], 'laptop')  # unknown chassis, has battery
        self.assertEqual(self.kind(ChassisTypes=[2])['DeviceType'], 'unknown')

    def test_branded_pc_keeps_its_name(self):
        d = self.kind(ChassisTypes=[3])
        self.assertEqual((d['Manufacturer'], d['Model'], d['IdentitySource']), ('Dell Inc.', 'OptiPlex 7090', 'system'))

    def test_custom_build_uses_motherboard(self):
        d = identify({'Manufacturer': 'System manufacturer', 'Model': 'System Product Name', 'ChassisTypes': [3],
                      'BoardManufacturer': 'Micro-Star International Co., Ltd.', 'BoardProduct': 'MAG B650 TOMAHAWK WIFI (MS-7D75)'})
        self.assertEqual((d['Manufacturer'], d['Model'], d['IdentitySource']), ('Micro-Star International Co., Ltd.', 'MAG B650 TOMAHAWK WIFI (MS-7D75)', 'motherboard'))
        self.assertEqual(d['ReportedModel'], 'System Product Name')
        # The motherboard identity must be usable for parts research.
        plan = parts_research.plan(kind='RAM', manufacturer=d['Manufacturer'], model=d['Model'])
        self.assertEqual(plan['domains'][0], 'msi.com')

    def test_placeholders_everywhere_are_unknown(self):
        d = identify({'Manufacturer': 'To Be Filled By O.E.M.', 'Model': 'To Be Filled By O.E.M.', 'BoardManufacturer': 'Default string', 'BoardProduct': 'Default string'})
        self.assertEqual(d['IdentitySource'], 'unknown')

    def test_report_shows_type(self):
        page = report.build({'available': True, 'device_type': 'desktop', 'identified_by': 'motherboard', 'manufacturer': 'ASUSTeK', 'model': 'B550'}, None, {}, [], generated=datetime(2026, 10, 10))
        self.assertIn('Desktop (custom-built, identified by its motherboard)', page)

    def test_psu_research_profile(self):
        phrase, keywords = parts_research.part_profile('replacement power supply (PSU)')
        self.assertEqual(phrase, 'power supply PSU')
        self.assertTrue(__import__('re').search(keywords, 'corsair rm750 750w psu'))


class TestOtherAccountsRefused(LocalServer):
    def test_page_and_api_refuse_other_accounts(self):
        with patch('local_security.same_user', return_value=False):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/', headers={'Host': f'127.0.0.1:{self.port}'})
            with self.assertRaises(urllib.error.HTTPError) as page:
                urllib.request.urlopen(req, timeout=10)
            with page.exception as e:
                self.assertEqual(e.code, 403)
                self.assertIn(b'another Windows account', e.read())
            status, body = self.call('/api/report')
            self.assertEqual(status, 403)
            self.assertNotIn('csrf', body)
            self.assertEqual(self.call('/api/intent', {'question': 'hi'})[0], 403)

    def test_same_account_allowed(self):
        self.assertEqual(self.call('/api/report')[0], 200)


@unittest.skipUnless(os.name == 'nt', 'Windows TCP table')
class TestConnectionOwner(unittest.TestCase):
    def test_owner_of_real_connections(self):
        srv = socket.socket()
        srv.bind(('127.0.0.1', 0))
        srv.listen()
        port = srv.getsockname()[1]
        child = subprocess.Popen([sys.executable, '-c', f'import socket,time;s=socket.create_connection(("127.0.0.1",{port}));time.sleep(2)'])
        try:
            conn, addr = srv.accept()
            self.assertEqual(local_security.connection_pid(addr[1], port), child.pid)
            self.assertTrue(local_security.same_user(addr, port))
            self.assertFalse(local_security.same_user(('127.0.0.1', 1), port))
            conn.close()
        finally:
            child.wait()
            srv.close()


@unittest.skipUnless(os.name == 'nt', 'Windows exclusive bind')
class TestPorts(unittest.TestCase):
    def test_exclusive_port_and_fallback(self):
        first = dashboard.start_server(48765)
        try:
            taken = first.server_address[1]
            with self.assertRaises(OSError):
                dashboard.start_server(taken, tries=1)  # nobody can bind on top of a running copy
            second = dashboard.start_server(taken)
            self.assertEqual(second.server_address[1], taken + 1)
            second.server_close()
        finally:
            first.server_close()


if __name__ == '__main__':
    unittest.main()
