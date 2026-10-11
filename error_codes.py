"""Error-code lookup: Windows Update errors, blue-screen stop codes, and anything Windows can explain itself.

Windows Update's own codes (0x8024xxxx, 0x800Fxxxx and the network ones) have no text in Windows, so the
common ones are listed here. Codes not listed get Windows' own message (FormatMessage) when it has one, or
an explanation of the family the code belongs to. Advice is for the person to follow; PC Medic changes nothing.
"""
import re

import bluescreen

TROUBLESHOOT = 'Run the Windows Update troubleshooter (Settings > System > Troubleshoot > Other troubleshooters), then try again.'
RESET = 'If it keeps failing, a technician can reset Windows Update: stop the wuauserv, bits and cryptsvc services, rename C:\\Windows\\SoftwareDistribution and System32\\catroot2, and start the services again.'
DISM = 'As administrator, run DISM /Online /Cleanup-Image /RestoreHealth, then sfc /scannow, then try the update again.'
RESTART = 'Restart the PC, then try the update again.'
NETWORK = 'Check the internet connection, turn off any VPN or proxy for a moment, and try again later.'

# code: (Windows name or None, what it means, what to do)
UPDATE_ERRORS = {
    0x80070002: ('ERROR_FILE_NOT_FOUND', 'Windows Update couldn’t find files it downloaded earlier.', TROUBLESHOOT + ' ' + RESET),
    0x80070003: ('ERROR_PATH_NOT_FOUND', 'Windows Update couldn’t find a folder it needs.', TROUBLESHOOT + ' ' + RESET),
    0x80070005: ('E_ACCESSDENIED', 'Windows Update was denied access to a file or setting.', 'Restart and try again. Third-party antivirus can cause this; ' + TROUBLESHOOT[0].lower() + TROUBLESHOOT[1:]),
    0x8007000D: ('ERROR_INVALID_DATA', 'A downloaded update file is damaged.', TROUBLESHOOT + ' ' + RESET),
    0x8007000E: ('E_OUTOFMEMORY', 'Windows ran short of memory or resources while installing.', 'Close other apps, restart, and try again.'),
    0x80070020: ('ERROR_SHARING_VIOLATION', 'Another program had a file open that the update needed, often antivirus or backup software.', RESTART),
    0x80070070: ('ERROR_DISK_FULL', 'There isn’t enough free space on the drive to install the update.', 'Free up space on drive C: (Tools > Find big files, or Windows cleanup suggestions), then try again.'),
    0x80070422: ('ERROR_SERVICE_DISABLED', 'The Windows Update service is turned off.', 'In Services, set Windows Update to Manual (the default) and start it, or ask whoever manages this PC.'),
    0x800705B4: ('ERROR_TIMEOUT', 'The update took too long and timed out.', RESTART),
    0x800706BA: ('RPC_S_SERVER_UNAVAILABLE', 'A Windows service the update needed didn’t respond.', RESTART),
    0x80070643: ('ERROR_INSTALL_FAILURE', 'The update’s installer reported a fatal error. Common with .NET, Microsoft Defender platform and Windows Recovery Environment updates.', 'Restart and try again. If it’s a Windows Recovery Environment update (such as KB5034441), the recovery partition may be too small; Microsoft’s article for that update explains the fix.'),
    0x80073712: ('ERROR_SXS_COMPONENT_STORE_CORRUPT', 'Windows’ component store, which updates are installed into, is damaged.', DISM),
    0x80073D02: ('ERROR_PACKAGES_IN_USE', 'A Microsoft Store app was open while its update installed.', 'Nothing to do: it usually succeeds on a later try. Closing the app helps.'),
    0x800F081F: ('CBS_E_SOURCE_MISSING', 'Windows couldn’t find the files it needed to install the update.', DISM),
    0x800F0831: ('CBS_E_STORE_CORRUPTION', 'Windows’ component store is missing something an update depends on.', DISM),
    0x800F0922: ('CBS_E_INSTALLERS_FAILED', 'The update couldn’t finish installing. Often a VPN blocking Windows Update, or a System Reserved partition that is too small.', 'Disconnect any VPN and try again. ' + DISM),
    0x800F0823: ('CBS_E_NEW_SERVICING_STACK_REQUIRED', 'This update needs a newer servicing stack (the part of Windows that installs updates) first.', 'Install the other available updates, restart, and try again; Windows usually installs the servicing stack update first.'),
    0x800F0988: (None, 'Windows couldn’t apply the update to its component store.', 'As administrator, run DISM /Online /Cleanup-Image /StartComponentCleanup, restart, and try again.'),
    0x80240016: ('WU_E_INSTALL_NOT_ALLOWED', 'Another installation was already running, or a restart was pending.', RESTART),
    0x80240017: ('WU_E_NOT_APPLICABLE', 'The update doesn’t apply to this PC.', 'Nothing to do.'),
    0x8024001E: ('WU_E_SERVICE_STOP', 'The update stopped because the service was shutting down.', RESTART),
    0x80240022: ('WU_E_ALL_UPDATES_FAILED', 'Every update in the batch failed.', TROUBLESHOOT + ' ' + RESET),
    0x80240034: ('WU_E_DOWNLOAD_FAILED', 'The update didn’t download completely.', NETWORK + ' ' + TROUBLESHOOT),
    0x80242014: ('WU_E_UH_POSTREBOOTSTILLPENDING', 'The update is waiting for a restart to finish.', 'Restart the PC.'),
    0x80242016: ('WU_E_UH_POSTREBOOTUNEXPECTEDSTATE', 'After restarting, the update was in a state Windows didn’t expect.', 'Try the update again; if it repeats, ' + TROUBLESHOOT[0].lower() + TROUBLESHOOT[1:]),
    0x8024200B: ('WU_E_UH_INSTALLERFAILURE', 'The update’s own installer failed. This is common with driver and firmware updates.', 'If it’s a driver, install that driver from the PC or device maker’s website instead; Windows stops offering it once you have the same or newer version.'),
    0x8024401C: ('WU_E_PT_HTTP_STATUS_REQUEST_TIMEOUT', 'The update server didn’t answer in time.', NETWORK),
    0x80244022: ('WU_E_PT_HTTP_STATUS_SERVICE_UNAVAIL', 'The update server was busy (HTTP 503).', 'Try again later.'),
    0x8024402C: ('WU_E_PT_WINHTTP_NAME_NOT_RESOLVED', 'The PC couldn’t look up the update server’s address (DNS).', NETWORK),
    0x8024402F: ('WU_E_PT_ECP_SUCCEEDED_WITH_ERRORS', 'Update information downloaded with errors, often because of a proxy or firewall.', NETWORK),
    0x80246007: ('WU_E_DM_NOTDOWNLOADED', 'The update hadn’t finished downloading.', NETWORK),
    0x80248007: ('WU_E_DS_NODATA', 'Windows Update’s own database is missing information.', TROUBLESHOOT + ' ' + RESET),
    0x80072EE2: ('ERROR_INTERNET_TIMEOUT', 'The connection to the update server timed out.', NETWORK),
    0x80072EE7: ('ERROR_INTERNET_NAME_NOT_RESOLVED', 'The PC couldn’t look up the update server’s address.', NETWORK),
    0x80072EFD: ('ERROR_INTERNET_CANNOT_CONNECT', 'The PC couldn’t connect to the update server.', NETWORK),
    0x80072F8F: ('ERROR_INTERNET_SECURE_FAILURE', 'A secure connection to the update server failed. A wrong date or time on the PC is the usual cause.', 'Check the date, time and time zone (Settings > Time & language), then try again.'),
}
# Common codes from programs and Windows itself (NTSTATUS), in plain words.
APP_ERRORS = {
    0xC0000005: ('STATUS_ACCESS_VIOLATION', 'A program tried to use memory it isn’t allowed to, so Windows closed it.', 'Update or reinstall the program that showed it. If many programs do this, run Windows Memory Diagnostic and the deep scan.'),
    0xC000021A: ('STATUS_SYSTEM_PROCESS_TERMINATED', 'A core Windows process ended unexpectedly, so Windows couldn’t keep running.', 'Often damaged system files or a recent update or driver. Use Advanced startup to uninstall the latest update or run Startup Repair, then run the deep scan.'),
    0xC0000142: ('STATUS_DLL_INIT_FAILED', 'A program couldn’t start because one of its components failed to load.', 'Restart, then reinstall the program. Updating the Microsoft Visual C++ and .NET runtimes often fixes it.'),
    0xC000007B: ('STATUS_INVALID_IMAGE_FORMAT', 'A program tried to load a component built for a different version of Windows (32-bit vs 64-bit).', 'Reinstall the program, and install the Microsoft Visual C++ runtimes it needs.'),
}
FAMILIES = [
    (0xFFFFF000, 0x80244000, 'A Windows Update network or proxy error.', NETWORK),
    (0xFFFFF000, 0x80245000, 'A Windows Update network error.', NETWORK),
    (0xFFFF0000, 0x80240000, 'A Windows Update error.', TROUBLESHOOT),
    (0xFFFF0000, 0x800F0000, 'An error from the part of Windows that installs updates (servicing).', DISM),
    (0xFFFF0000, 0x80190000, 'A download error returned by a web server.', NETWORK),
    (0xFFFF0000, 0x80072000, 'An internet connection error.', NETWORK),
    (0xF0000000, 0xC0000000, 'A Windows status code, usually from a program that crashed.', 'If one program keeps showing it, update or reinstall that program. If many programs do, run the deep scan and Windows Memory Diagnostic.'),
]
CODE_RE = re.compile(r'\b0x[0-9a-f]{1,8}\b|\b8[0-9a-f]{7}\b', re.I)  # also "error 80070643" without the 0x


def windows_message(code):
    """Windows' own text for a code, if it has one."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetModuleHandleW.restype = ctypes.c_void_p
        buf = ctypes.create_unicode_buffer(1024)
        n = k.FormatMessageW(0x1000 | 0x200, None, ctypes.c_uint32(code), 0, buf, 1024, None)
        if not n and code & 0xC0000000 == 0xC0000000:  # NTSTATUS codes (app crashes such as 0xC0000005) live in ntdll
            n = k.FormatMessageW(0x800 | 0x200, ctypes.c_void_p(k.GetModuleHandleW('ntdll.dll')), ctypes.c_uint32(code), 0, buf, 1024, None)
        text = re.sub(r'\s+', ' ', buf.value).strip() if n else None
        if text:  # message templates contain blanks like 0x%p and {Titles}
            text = re.sub(r'\{[^}]*\}\s*', '', re.sub(r'(0x)?%\w+', '…', text)).strip()
        return text or None
    except (AttributeError, OSError):
        return None


def find_code(text):
    m = CODE_RE.search(text or '')
    return int(m.group(0)[2:] if m.group(0).lower().startswith('0x') else m.group(0), 16) if m else None


def lookup(code):
    """{'code','kind','name','meaning','fix','source'} for an error code (int or '0x...' text)."""
    if isinstance(code, str):
        code = find_code(code)
    if code is None:
        return None
    text = f'0x{code:08X}'
    if code in UPDATE_ERRORS:
        name, meaning, fix = UPDATE_ERRORS[code]
        return {'code': text, 'kind': 'Windows Update', 'name': name, 'meaning': meaning, 'fix': fix, 'source': 'PC Medic’s list of common Windows Update errors'}
    if code in APP_ERRORS:
        name, meaning, fix = APP_ERRORS[code]
        return {'code': text, 'kind': 'Program or Windows error', 'name': name, 'meaning': meaning, 'fix': fix, 'source': 'PC Medic’s list of common error codes'}
    if code < 0x1000:  # blue-screen stop codes are small numbers
        b = bluescreen.explain(code)
        return {'code': text, 'kind': 'Blue screen stop code', 'name': b['name'], 'meaning': b['meaning'], 'fix': b['advice'], 'source': 'PC Medic’s list of stop codes'}
    message = windows_message(code)
    family = next(((m, f) for mask, value, m, f in FAMILIES if code & mask == value), None)
    if message:
        return {'code': text, 'kind': 'Windows error', 'name': None, 'meaning': message, 'fix': family[1] if family else 'Search the code with the name of the program that showed it.', 'source': 'Windows’ own description'}
    if family:
        return {'code': text, 'kind': 'Windows Update' if family[0].startswith(('A Windows Update', 'An error from the part')) else 'Windows error',
                'name': None, 'meaning': family[0] + ' PC Medic doesn’t have this exact code in its list.', 'fix': family[1], 'source': 'the code’s error family'}
    return {'code': text, 'kind': 'Unknown', 'name': None, 'meaning': 'PC Medic and Windows don’t have a description for this code.', 'fix': 'Search the code together with the name of the program that showed it, or ask Claude.', 'source': None}


def describe(info, technical=False):
    if not info:
        return 'PC Medic didn’t find an error code like 0x80070643 in that question.'
    if technical:
        return f'{info["code"]}{" " + info["name"] if info.get("name") else ""} · {info["kind"]} · {info["meaning"]} · Fix: {info["fix"]} (source: {info["source"] or "none"})'
    head = f'Error {info["code"]}' + (f' ({info["name"]})' if info.get('name') else '') + f' · {info["kind"]}'
    return f'{head}\n\nWhat it means: {info["meaning"]}\n\nWhat to do: {info["fix"]}'
