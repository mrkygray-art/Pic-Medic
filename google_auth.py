"""Google sign-in, required for PC Medic's free AI questions (the trial). The user's own API key never needs it.

OAuth 2.0 for desktop apps: the sign-in page opens in the default browser, Google redirects to a one-time listener on
127.0.0.1 (random port, closed after one sign-in or SIGN_IN_TIMEOUT), and PKCE plus a random state protect the code.
Scopes are only 'openid email'. PC Medic keeps the account id (sub) and email in Windows Credential Manager and
discards Google's tokens right away, so there is nothing to refresh or revoke. Signing in sends nothing about this PC.

The OAuth client is a Google Cloud "Desktop app" client. Google documents that a desktop client's secret can't be
kept secret, so shipping it in the app is expected (unlike an AI key). PCMEDIC_GOOGLE_CLIENT_ID and
PCMEDIC_GOOGLE_CLIENT_SECRET override the built-in values.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import settings

# Filled in from the Google Cloud console (APIs & Services > Credentials > OAuth client ID > Desktop app).
DEFAULT_CLIENT_ID = ''
DEFAULT_CLIENT_SECRET = ''
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
ISSUERS = ('https://accounts.google.com', 'accounts.google.com')
SCOPES = 'openid email'
SIGN_IN_TIMEOUT = 300  # seconds the browser has to finish signing in
CREDENTIAL = 'google'  # Credential Manager target PCMedic/google
LOCK = threading.Lock()
FLOW = {'status': 'idle', 'error': None}  # idle | waiting | signed_in | cancelled | failed


def client():
    return (os.environ.get('PCMEDIC_GOOGLE_CLIENT_ID', '').strip() or DEFAULT_CLIENT_ID,
            os.environ.get('PCMEDIC_GOOGLE_CLIENT_SECRET', '').strip() or DEFAULT_CLIENT_SECRET)


def configured():
    return bool(client()[0])


def account():
    """{'sub', 'email'} for the signed-in Google account, or None."""
    try:
        data = json.loads(settings.load_key(CREDENTIAL) or 'null')
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('sub') else None


def sign_out():
    settings.delete_key(CREDENTIAL)
    with LOCK:
        FLOW.update(status='idle', error=None)


def status():
    """What the Settings screen shows: never tokens, only the email the user signed in with."""
    acct = account()
    with LOCK:
        flow = dict(FLOW)
    return {'configured': configured(), 'signed_in': bool(acct), 'email': (acct or {}).get('email'),
            'pending': flow['status'] == 'waiting', 'error': flow['error'] if flow['status'] in ('cancelled', 'failed') else None}


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def claims(id_token, client_id, now=None):
    """Read and check the ID token. It came straight from Google's token endpoint over TLS, so per OpenID Connect
    its signature needn't be verified here; issuer, audience and expiry still are."""
    try:
        payload = id_token.split('.')[1]
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (AttributeError, IndexError, ValueError):
        raise ValueError('Google returned an unreadable sign-in token.') from None
    if data.get('iss') not in ISSUERS or data.get('aud') != client_id:
        raise ValueError('The sign-in token was not issued for PC Medic.')
    if float(data.get('exp', 0)) < (now or time.time()):
        raise ValueError('The sign-in token has expired. Try signing in again.')
    if not data.get('sub'):
        raise ValueError('Google did not return an account id.')
    return {'sub': str(data['sub']), 'email': str(data.get('email') or '') if data.get('email_verified', True) else ''}


def _exchange(code, verifier, redirect_uri, fetch=None):
    client_id, client_secret = client()
    form = {'code': code, 'client_id': client_id, 'redirect_uri': redirect_uri, 'grant_type': 'authorization_code', 'code_verifier': verifier}
    if client_secret:
        form['client_secret'] = client_secret
    if fetch:
        tokens = fetch(TOKEN_URL, form)
    else:
        req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                tokens = json.loads(r.read(100000))
        except urllib.error.HTTPError as exc:
            raise ValueError(f'Google did not accept the sign-in (HTTP {exc.code}). Try again.') from None
        except (urllib.error.URLError, TimeoutError):
            raise ValueError('Could not reach Google to finish signing in. Check the internet connection.') from None
    return claims(tokens.get('id_token'), client_id)


PAGE = ('<!doctype html><meta charset="utf-8"><title>PC Medic</title><body style="font:16px Segoe UI,sans-serif;'
        'max-width:520px;margin:15vh auto;padding:0 16px"><h2>{title}</h2><p>{text}</p></body>')


def start(open_browser=None, fetch=None):
    """Open Google's sign-in page and wait (in the background) for its redirect. Returns the sign-in URL."""
    client_id, _ = client()
    if not client_id:
        raise RuntimeError('Google sign-in is not set up in this copy of PC Medic.')
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    done = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, title, text, code=200):
            body = PAGE.format(title=title, text=text).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != '/':
                return self.reply('Not found', '', 404)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if not secrets.compare_digest(q.get('state', ''), state):
                return self.reply('Sign-in link expired', 'Start signing in again from PC Medic Settings.', 400)
            if q.get('error') or not q.get('code'):
                finish('cancelled', 'Google sign-in was cancelled.')
                return self.reply('Sign-in cancelled', 'You can close this tab. PC Medic did not sign in.')
            try:
                acct = _exchange(q['code'], verifier, redirect_uri, fetch)
                settings.save_key(CREDENTIAL, json.dumps(acct))
            except (ValueError, OSError) as exc:
                finish('failed', str(exc))
                return self.reply('Sign-in failed', str(exc) + ' Close this tab and try again from PC Medic Settings.')
            finish('signed_in', None)
            self.reply('You are signed in', 'PC Medic is signed in with Google. You can close this tab and go back to PC Medic.')

    def finish(result, error):
        with LOCK:
            if FLOW.get('state') == state:
                FLOW.update(status=result, error=error)
        done.set()

    server = HTTPServer(('127.0.0.1', 0), Callback)
    server.timeout = 1
    redirect_uri = f'http://127.0.0.1:{server.server_address[1]}/'
    url = AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': SCOPES, 'state': state,
        'code_challenge': _b64url(hashlib.sha256(verifier.encode('ascii')).digest()), 'code_challenge_method': 'S256',
        'prompt': 'select_account'})

    def serve():
        deadline = time.time() + SIGN_IN_TIMEOUT
        try:
            while not done.is_set() and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()
            if not done.is_set():
                finish('cancelled', 'Google sign-in timed out. Try again.')

    with LOCK:
        old = FLOW.get('done')
        FLOW.update(status='waiting', error=None, state=state, done=done)
    if old:  # a new attempt replaces an unfinished one; its listener closes within a second
        old.set()
    threading.Thread(target=serve, daemon=True, name='google-sign-in').start()
    if open_browser is None:
        import webbrowser
        open_browser = webbrowser.open
    open_browser(url)
    return url
