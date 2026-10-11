"""API keys, the AI trial allowance and update checks.

Key sources, in order:
  1. 'saved'       - the user's own key, saved in Settings (Windows Credential Manager, encrypted for this Windows account)
  2. 'environment' - ANTHROPIC_API_KEY / OPENAI_API_KEY on this PC (a developer's own key)
  3. 'trial'       - PC Medic's included key, limited to TRIAL_LIMIT AI questions per Windows account
Keys never go to the browser; the UI only sees which source is in use.

WARNING before public release: a trial key shipped inside the .exe can be extracted and the local counter can be
reset. Move the trial behind a small service that holds the key (TRIAL_* settings are the hook for that).
"""
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from version import VERSION

PROVIDERS = {'anthropic': 'ANTHROPIC_API_KEY', 'openai': 'OPENAI_API_KEY'}
KEY_FORMAT = {'anthropic': re.compile(r'sk-ant-[A-Za-z0-9_\-]{20,300}'), 'openai': re.compile(r'sk-[A-Za-z0-9_\-]{20,300}')}
TRIAL_LIMIT = 10
CREDENTIAL_PREFIX = 'PCMedic'
# GitHub project whose Releases carry the installers. PCMEDIC_UPDATE_REPO overrides it; '' disables update checks.
UPDATE_REPO = os.environ.get('PCMEDIC_UPDATE_REPO', 'mrkygray-art/Pic-Medic')
DATA_FILE = None  # set by dashboard.py: <data folder>/settings.json
IGNORE_ENVIRONMENT = False  # --ignore-env-keys: test the trial and Settings as a new user would
LOCK = threading.Lock()


class TrialExhausted(RuntimeError):
    pass


# ---------- Windows Credential Manager ----------
def _credential_api():
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [('low', wintypes.DWORD), ('high', wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                    ('LastWritten', FILETIME), ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_char)),
                    ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
    return ctypes, ctypes.WinDLL('advapi32', use_last_error=True), CREDENTIAL


def _target(provider):
    return f'{CREDENTIAL_PREFIX}/{provider}'


def save_key(provider, key):
    ctypes, advapi32, CREDENTIAL = _credential_api()
    blob = key.encode('utf-16-le')
    buffer = ctypes.create_string_buffer(blob, len(blob))
    cred = CREDENTIAL(Type=1, TargetName=_target(provider), CredentialBlobSize=len(blob),  # CRED_TYPE_GENERIC
                      CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)), Persist=2, UserName='PC Medic')  # CRED_PERSIST_LOCAL_MACHINE
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise OSError('Windows Credential Manager could not save the key')


def load_key(provider):
    if os.name != 'nt':
        return None
    ctypes, advapi32, CREDENTIAL = _credential_api()
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not advapi32.CredReadW(_target(provider), 1, 0, ctypes.byref(pointer)):
        return None
    try:
        cred = pointer.contents
        return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode('utf-16-le') or None
    finally:
        advapi32.CredFree(pointer)


def delete_key(provider):
    ctypes, advapi32, _ = _credential_api()
    advapi32.CredDeleteW(_target(provider), 1, 0)


# ---------- settings file (trial count, update preference) ----------
def _read():
    try:
        return json.loads(Path(DATA_FILE).read_text(encoding='utf-8')) if DATA_FILE and Path(DATA_FILE).exists() else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    if not DATA_FILE:
        return
    temp = Path(DATA_FILE).with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(DATA_FILE)


# ---------- key resolution and the trial ----------
def trial_key(provider):
    return os.environ.get(f'PCMEDIC_TRIAL_{PROVIDERS[provider]}', '').strip() or None


def resolve(provider):
    """(key, source) for a provider; (None, None) when nothing is configured."""
    saved = load_key(provider)
    if saved:
        return saved, 'saved'
    env = '' if IGNORE_ENVIRONMENT else os.environ.get(PROVIDERS[provider], '').strip()
    if env:
        return env, 'environment'
    trial = trial_key(provider)
    if trial:
        return trial, 'trial'
    return None, None


def trial_uses():
    return int(_read().get('trial_uses', 0))


def key_for_use(provider):
    """Key for one AI request; raises TrialExhausted once the trial allowance is spent."""
    key, source = resolve(provider)
    if not key:
        return None, None
    if source == 'trial' and trial_uses() >= TRIAL_LIMIT:
        raise TrialExhausted(f'You have used the {TRIAL_LIMIT} free AI questions included with PC Medic. '
                             'Add your own Anthropic or OpenAI API key in Settings to keep using AI. Offline answers still work.')
    return key, source


def record_use(source):
    """Count a completed AI request against the trial (own keys are never counted)."""
    if source != 'trial':
        return
    with LOCK:
        data = _read()
        data['trial_uses'] = int(data.get('trial_uses', 0)) + 1
        _write(data)


def available(provider):
    try:
        return key_for_use(provider)[0] is not None
    except TrialExhausted:
        return False


def verify_key(provider, key):
    """Check a key with the provider's free model-list endpoint before saving it."""
    if not KEY_FORMAT[provider].fullmatch(key):
        raise ValueError('That does not look like an ' + ('Anthropic key (sk-ant-…)' if provider == 'anthropic' else 'OpenAI key (sk-…)') + '.')
    if provider == 'anthropic':
        url, headers = 'https://api.anthropic.com/v1/models?limit=1', {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    else:
        url, headers = 'https://api.openai.com/v1/models', {'Authorization': 'Bearer ' + key}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError('The provider rejected this key. Check that you copied all of it.') from None
        raise RuntimeError(f'Could not verify the key right now (HTTP {exc.code}). Try again later.') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Could not reach the provider to verify the key. Check the internet connection.') from None


def summary():
    """What the Settings screen shows. Never includes key values."""
    uses = trial_uses()
    out = {'providers': {}, 'trial': {'limit': TRIAL_LIMIT, 'used': uses, 'remaining': max(0, TRIAL_LIMIT - uses)},
           'updates': {'enabled': update_checks_enabled(), 'repo': UPDATE_REPO, 'version': VERSION}}
    for provider in PROVIDERS:
        key, source = resolve(provider)
        out['providers'][provider] = {'configured': bool(key), 'source': source, 'available': available(provider)}
    return out


# ---------- updates (GitHub Releases) ----------
def update_checks_enabled():
    return bool(UPDATE_REPO) and _read().get('update_checks', True)


def set_update_checks(enabled):
    with LOCK:
        data = _read()
        data['update_checks'] = bool(enabled)
        _write(data)


def _version_tuple(text):
    numbers = re.findall(r'\d+', str(text))[:3]
    return tuple(int(n) for n in numbers + ['0'] * (3 - len(numbers)))


def check_for_update(fetch=None):
    """Compare the latest GitHub release with VERSION. Sends only a plain request to GitHub; nothing about this PC."""
    if not update_checks_enabled():
        return {'enabled': False}
    url = f'https://api.github.com/repos/{UPDATE_REPO}/releases/latest'
    try:
        if fetch:
            release = fetch(url)
        else:
            req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': f'PCMedic/{VERSION}'})
            with urllib.request.urlopen(req, timeout=10) as r:
                release = json.loads(r.read(200000))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # GitHub answers 404 until the first release is published
            return {'enabled': True, 'available': False, 'latest': None, 'note': 'No releases have been published yet.'}
        return {'enabled': True, 'error': 'Could not check for updates right now.'}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {'enabled': True, 'error': 'Could not check for updates right now.'}
    latest = str(release.get('tag_name') or '')
    page = str(release.get('html_url') or '')
    newer = _version_tuple(latest) > _version_tuple(VERSION)
    # Link straight to the Windows installer when the release has one, so people don't hunt through "Assets".
    installers = [a for a in release.get('assets') or [] if isinstance(a, dict)
                  and str(a.get('name', '')).lower().endswith(('.exe', '.msi', '.msix'))
                  and str(a.get('browser_download_url', '')).startswith('https://github.com/')
                  and not re.search(r'arm64|32-?bit|portable|debug', str(a.get('name', '')), re.I)]
    return {'enabled': True, 'available': newer and page.startswith('https://github.com/'), 'latest': latest.lstrip('v'),
            'url': page if page.startswith('https://github.com/') else None,
            'installer': installers[0]['browser_download_url'] if installers else None,
            'installer_name': installers[0].get('name') if installers else None,
            'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
