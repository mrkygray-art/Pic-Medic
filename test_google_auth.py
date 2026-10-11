"""Google sign-in for the free trial: the loopback flow, ID-token checks, and no free AI without a sign-in (no network)."""
import base64
import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import google_auth
import settings

CLIENT = 'test-client.apps.googleusercontent.com'
TRIAL_ENV = {'PCMEDIC_TRIAL_ANTHROPIC_API_KEY': 'trial-key', 'PCMEDIC_GOOGLE_CLIENT_ID': CLIENT, 'PCMEDIC_GOOGLE_CLIENT_SECRET': 'desktop-secret'}


def token(**over):
    data = {'iss': 'https://accounts.google.com', 'aud': CLIENT, 'sub': '1234567890', 'email': 'ky@example.com',
            'email_verified': True, 'exp': time.time() + 600, **over}
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()
    return part({'alg': 'RS256'}) + '.' + part(data) + '.signature'


class FakeVault:
    """Stands in for Windows Credential Manager."""
    def __init__(self):
        self.items = {}
        self.patches = [patch('settings.load_key', side_effect=self.items.get), patch('settings.save_key', side_effect=self.items.__setitem__),
                        patch('settings.delete_key', side_effect=lambda k: self.items.pop(k, None))]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class TestClaims(unittest.TestCase):
    def test_good_token(self):
        self.assertEqual(google_auth.claims(token(), CLIENT), {'sub': '1234567890', 'email': 'ky@example.com'})

    def test_rejects_other_audience_issuer_or_expired(self):
        for bad in (token(aud='someone-else'), token(iss='https://evil.example'), token(exp=time.time() - 5), token(sub=''), 'not-a-token'):
            with self.assertRaises(ValueError):
                google_auth.claims(bad, CLIENT)

    def test_unverified_email_is_not_kept(self):
        self.assertEqual(google_auth.claims(token(email_verified=False), CLIENT)['email'], '')


class TestTrialNeedsSignIn(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for p in (patch('settings.DATA_FILE', os.path.join(self.dir, 'settings.json')), patch.dict('os.environ', TRIAL_ENV, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.vault = FakeVault().__enter__()
        self.addCleanup(self.vault.__exit__)

    def test_no_free_questions_before_sign_in(self):
        with self.assertRaisesRegex(settings.SignInRequired, 'Sign in with Google in Settings'):
            settings.key_for_use('anthropic')
        self.assertFalse(settings.available('anthropic'))
        self.assertEqual(settings.trial_uses(), 0)

    def test_sign_in_is_a_trial_exhausted_error_for_existing_callers(self):
        self.assertTrue(issubclass(settings.SignInRequired, settings.TrialExhausted))

    def test_free_questions_after_sign_in_and_stop_after_sign_out(self):
        self.vault.items['google'] = json.dumps({'sub': '1', 'email': 'ky@example.com'})
        self.assertEqual(settings.key_for_use('anthropic'), ('trial-key', 'trial'))
        google_auth.sign_out()
        with self.assertRaises(settings.SignInRequired):
            settings.key_for_use('anthropic')

    def test_own_key_never_needs_sign_in(self):
        self.vault.items['anthropic'] = 'saved-key'
        self.assertEqual(settings.key_for_use('anthropic'), ('saved-key', 'saved'))

    def test_summary_shows_email_but_no_tokens(self):
        self.vault.items['google'] = json.dumps({'sub': '1', 'email': 'ky@example.com'})
        g = settings.summary()['google']
        self.assertEqual((g['configured'], g['signed_in'], g['email']), (True, True, 'ky@example.com'))
        self.assertNotIn('sub', g)

    def test_summary_says_whether_a_trial_is_offered(self):
        self.assertTrue(settings.summary()['trial']['offered'])
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(settings.summary()['trial']['offered'])

    def test_corrupt_saved_account_counts_as_signed_out(self):
        self.vault.items['google'] = '{not json'
        self.assertIsNone(google_auth.account())


class TestLoopbackFlow(unittest.TestCase):
    def setUp(self):
        p = patch.dict('os.environ', {'PCMEDIC_GOOGLE_CLIENT_ID': CLIENT, 'PCMEDIC_GOOGLE_CLIENT_SECRET': 'desktop-secret'}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.vault = FakeVault().__enter__()
        self.addCleanup(self.vault.__exit__)
        self.addCleanup(google_auth.sign_out)
        self.sent = []

    def begin(self):
        opened = []
        fetch = lambda url, form: self.sent.append((url, form)) or {'id_token': token(), 'access_token': 'discarded'}
        google_auth.start(open_browser=opened.append, fetch=fetch)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query).items()}
        return q

    def visit(self, q, **params):
        url = q['redirect_uri'] + '?' + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def wait(self, status):
        for _ in range(50):
            if google_auth.FLOW['status'] == status:
                return
            time.sleep(0.05)
        self.fail('flow stayed ' + google_auth.FLOW['status'])

    def test_sign_in_request_uses_pkce_loopback_and_minimal_scopes(self):
        q = self.begin()
        self.assertEqual((q['client_id'], q['scope'], q['code_challenge_method'], q['response_type']), (CLIENT, 'openid email', 'S256', 'code'))
        self.assertRegex(q['redirect_uri'], r'^http://127\.0\.0\.1:\d+/$')
        self.assertTrue(google_auth.status()['pending'])
        self.visit(q, state=q['state'], error='access_denied')

    def test_successful_sign_in_saves_only_the_account(self):
        q = self.begin()
        status, page = self.visit(q, state=q['state'], code='auth-code')
        self.assertEqual(status, 200)
        self.assertIn('signed in', page)
        self.wait('signed_in')
        url, form = self.sent[0]
        self.assertEqual((url, form['code'], form['client_secret'], form['redirect_uri']), (google_auth.TOKEN_URL, 'auth-code', 'desktop-secret', q['redirect_uri']))
        self.assertTrue(form['code_verifier'])
        self.assertEqual(json.loads(self.vault.items['google']), {'sub': '1234567890', 'email': 'ky@example.com'})
        self.assertNotIn('discarded', self.vault.items['google'])
        self.assertEqual(google_auth.status()['email'], 'ky@example.com')

    def test_wrong_state_is_refused_and_nothing_is_saved(self):
        q = self.begin()
        status, _ = self.visit(q, state='forged', code='auth-code')
        self.assertEqual(status, 400)
        self.assertEqual(self.sent, [])
        self.assertNotIn('google', self.vault.items)
        self.visit(q, state=q['state'], error='access_denied')

    def test_cancel_in_browser(self):
        q = self.begin()
        self.visit(q, state=q['state'], error='access_denied')
        self.wait('cancelled')
        self.assertEqual(google_auth.status()['error'], 'Google sign-in was cancelled.')

    def test_client_file_from_google_console(self):
        path = google_auth.Path(tempfile.mkdtemp()) / 'google_client.json'
        path.write_text(json.dumps({'installed': {'client_id': 'file-id', 'client_secret': 'file-secret'}}), encoding='utf-8')
        with patch.dict('os.environ', {}, clear=True), patch('google_auth.CLIENT_FILE', path):
            self.assertEqual(google_auth.client(), ('file-id', 'file-secret'))

    def test_not_configured(self):
        with patch.dict('os.environ', {}, clear=True), patch('google_auth.CLIENT_FILE', google_auth.Path(tempfile.mkdtemp()) / 'none.json'):
            self.assertFalse(google_auth.configured())
            with self.assertRaisesRegex(RuntimeError, 'not set up'):
                google_auth.start(open_browser=lambda u: None)


if __name__ == '__main__':
    unittest.main()
