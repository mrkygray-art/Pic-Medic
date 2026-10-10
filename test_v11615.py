"""1.16.15: conversation routing, honest parts research and HTTP contracts.
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
import parts_research
from hardware_advisor import clean_product_name
from intent_engine import classify

PENDING = {'pending_research': 'RAM'}


class TestIntentAcceptance(unittest.TestCase):
    """The acceptance table from the project handoff."""
    cases = [
        ('What is my IP address?', None, 'network_inventory'),
        ('What is my IP?', None, 'network_inventory'),
        ('What is the make and model?', None, 'hardware_inventory'),
        ('What type of RAM is installed?', None, 'hardware_inventory'),
        ('What GPU do I have?', None, 'hardware_inventory'),
        ('Can I add more memory?', None, 'memory_clarify'),
        ('What RAM do I have? Can I upgrade? Where can I buy it?', None, 'ram_upgrade'),
        ('Can I upgrade my SSD?', None, 'storage_upgrade'),
        ('I need a new charger', None, 'replacement_part'),
        ('Where can I buy a power adapter for this laptop?', None, 'replacement_part'),
        ('I need a replacement battery', None, 'replacement_part'),
        ('Yes, research it', PENDING, 'research_confirm'),
        ('yes please', PENDING, 'research_confirm'),
        ('Where can I buy it?', PENDING, 'research_confirm'),
        ('No thanks', PENDING, 'research_decline'),
        ("No, don't search", PENDING, 'research_decline'),
        ('Can you open PowerShell?', None, 'open_tool'),
        ('Can you open DOS?', None, 'open_tool'),
        ('How many ports do I have?', None, 'ports_clarify'),
        ('My computer froze', None, 'performance'),
    ]

    def test_acceptance_table(self):
        for question, context, intent in self.cases:
            with self.subTest(question=question):
                self.assertEqual(classify(question, context)['intent'], intent)

    def test_part_and_tool_slots(self):
        self.assertEqual(classify('I need a new charger')['part'], 'replacement laptop charger')
        self.assertEqual(classify('I need a replacement battery')['part'], 'replacement laptop battery')
        self.assertEqual(classify('Can you open PowerShell?')['tool'], 'powershell')
        self.assertEqual(classify('open command prompt')['tool'], 'command-prompt')

    def test_symptoms_are_not_shopping(self):
        self.assertEqual(classify('My laptop is not charging')['intent'], 'guided_knowledge')
        self.assertEqual(classify('My battery drains fast')['intent'], 'guided_knowledge')

    def test_affirmation_without_offer_does_not_research(self):
        r = classify('Yes, research it')
        self.assertEqual(r['intent'], 'clarify')
        self.assertIn('no search waiting', r['answer'])

    def test_new_question_while_offer_pending_is_not_a_reply(self):
        self.assertEqual(classify('What is my IP?', PENDING)['intent'], 'network_inventory')


class TestPartsResearch(unittest.TestCase):
    fields = dict(kind='replacement laptop charger', manufacturer='LENOVO', model='82XV', product_name='LOQ 15IRH8')

    def test_plan_is_oem_first_and_minimal(self):
        p = parts_research.plan(**self.fields)
        self.assertEqual(p['queries'][0], ('Manufacturer', 'LENOVO LOQ 15IRH8 82XV AC adapter charger site:lenovo.com'))
        self.assertEqual(set(parts_research.preview(**self.fields)['shared_fields']), {'manufacturer', 'model', 'product_name', 'kind'})

    def test_rejects_injection_characters(self):
        with self.assertRaises(ValueError):
            parts_research.plan(kind='charger', manufacturer='LENOVO', model='82XV"; <script>')

    def test_no_key_does_not_search_or_invent(self):
        with patch.dict('os.environ', {}, clear=True), patch('urllib.request.urlopen') as net:
            r = parts_research.research(**self.fields)
        net.assert_not_called()
        self.assertFalse(r['searched'])
        self.assertEqual(r['sources'], [])
        self.assertIn('not configured', r['errors'][0])
        self.assertTrue(all(link['url'].startswith('https://') for link in r['search_links']))

    def test_homepages_and_off_topic_hits_are_dropped(self):
        p = parts_research.plan(**self.fields)
        drop = [
            {'url': 'https://www.lenovo.com/us/en/', 'title': 'Laptops, Desktop PCs - Lenovo US', 'description': 'charger'},
            {'url': 'https://www.lenovo.com/us/en/pc/', 'title': 'Lenovo PCs', 'description': 'adapter'},
            {'url': 'https://support.lenovo.com/us/en/selectproduct', 'title': 'Lenovo Support', 'description': 'Parts Accessories adapter'},
            {'url': 'https://en.wikipedia.org/wiki/Lenovo', 'title': 'Lenovo - Wikipedia', 'description': 'company'},
            {'url': 'http://example.com/82xv-charger', 'title': '82XV charger', 'description': ''},
        ]
        for hit in drop:
            with self.subTest(url=hit['url']):
                self.assertIsNone(parts_research.assess(hit, p))

    def test_labels_never_claim_verified(self):
        p = parts_research.plan(**self.fields)
        exact = parts_research.assess({'url': 'https://www.amazon.com/dp/B0TEST', 'title': 'Lenovo LOQ 15IRH8 230W charger', 'description': ''}, p)
        generic = parts_research.assess({'url': 'https://www.cdw.com/product/lenovo-170w-ac-adapter/123', 'title': 'Lenovo 170W AC adapter', 'description': ''}, p)
        oem = parts_research.assess({'url': 'https://psref.lenovo.com/Product/LOQ/LOQ_15IRH8', 'title': 'LOQ 15IRH8 PSREF', 'description': 'AC adapter 170W or 230W'}, p)
        self.assertEqual((exact['match'], exact['source_type']), ('possible', 'retailer'))
        self.assertEqual((generic['match'], generic['source_type']), ('unverified', 'retailer'))
        self.assertEqual(oem['source_type'], 'manufacturer')

    def test_brave_results_are_filtered_and_errors_reported(self):
        hits = [{'url': 'https://www.lenovo.com/us/en/', 'title': 'Lenovo US', 'description': 'charger'},
                {'url': 'https://www.amazon.com/dp/B0X', 'title': 'Charger for Lenovo LOQ 15IRH8 82XV', 'description': '230W'}]
        calls = []
        def fake(query, key):
            calls.append(query)
            if 'site:' in query:
                raise urllib.error.HTTPError('u', 429, 'too many', {}, None)
            return hits
        with patch.dict('os.environ', {'BRAVE_SEARCH_API_KEY': 'test'}), patch('parts_research._brave', side_effect=fake):
            r = parts_research.research(**self.fields)
        self.assertTrue(r['searched'])
        self.assertEqual([s['url'] for s in r['sources']], ['https://www.amazon.com/dp/B0X'])
        self.assertIn('rate limit', r['errors'][0])
        self.assertEqual(len(calls), 2)


class TestHardwareHelpers(unittest.TestCase):
    def test_product_name_placeholders(self):
        self.assertEqual(clean_product_name('LOQ 15IRH8'), 'LOQ 15IRH8')
        for junk in ('To be filled by O.E.M.', '1.0', '', None, 'System Version'):
            self.assertEqual(clean_product_name(junk), '')


class TestHttpContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        cls.server.demo = True
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token is not False:
            headers['X-PC-Medic-Token'] = token or dashboard.TOKEN
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method='GET' if body is None else 'POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_report_supplies_csrf_token(self):
        status, body = self.call('/api/report')
        self.assertEqual(status, 200)
        self.assertEqual(body['csrf'], dashboard.TOKEN)

    def test_post_requires_token(self):
        self.assertEqual(self.call('/api/intent', {'question': 'hi'}, token=False)[0], 403)

    def test_intent_uses_conversation_context(self):
        status, body = self.call('/api/intent', {'question': 'Yes, research it', 'context': {'pending_research': 'RAM'}})
        self.assertEqual((status, body['intent']), (200, 'research_confirm'))

    def test_research_requires_approval(self):
        status, body = self.call('/api/parts-research', {'kind': 'RAM', 'manufacturer': 'LENOVO', 'model': '82XV'})
        self.assertEqual(status, 403)

    def test_preview_needs_no_approval_and_sends_nothing(self):
        with patch('parts_research._brave') as net:
            status, body = self.call('/api/parts-research-preview', {'kind': 'RAM', 'manufacturer': 'LENOVO', 'model': '82XV'})
        self.assertEqual(status, 200)
        self.assertIn('queries', body)
        net.assert_not_called()

    def test_approved_research_without_key_reports_not_configured(self):
        with patch.dict('os.environ', {}, clear=True):
            status, body = self.call('/api/parts-research', {'approved': True, 'kind': 'replacement laptop charger', 'manufacturer': 'LENOVO', 'model': '82XV'})
        self.assertEqual((status, body['searched']), (200, False))
        self.assertTrue(body['search_links'])

    def test_hardware_endpoint_is_get_only(self):
        self.assertEqual(self.call('/api/hardware-upgrade', {})[0], 404)


if __name__ == '__main__':
    unittest.main()
