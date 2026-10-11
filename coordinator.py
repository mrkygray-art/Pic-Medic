"""Diagnostic coordinator: turn a problem ("my computer keeps freezing") into an investigation.

1. Pick a playbook for the symptom.
2. Run that playbook's existing read-only routines in parallel (system_checks, a short performance sample,
   the "What changed?" timeline, the latest deep scan).
3. Correlate the evidence with technician rules: each finding says what it points to, how strongly,
   and which test would confirm it.
4. Rank the next tests.

The result stands on its own offline. When Claude is available, the page hands it to Claude (assistant.py),
which can run more checks, correlate further and pick the next test with recommend_next_test.
Everything here only reads; tests are things the user starts.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import system_checks

as_list = system_checks.as_list

PLAYBOOKS = {
    'freeze': {'title': 'Freezing or not responding', 'checks': ['event_signals', 'crashes', 'disk_health', 'pending_reboot', 'updates'], 'perf': True, 'default': ['watch', 'reliability']},
    'crash': {'title': 'Crashes, blue screens or restarts', 'checks': ['crashes', 'event_signals', 'updates', 'disk_health', 'pending_reboot'], 'perf': False, 'default': ['deep_scan', 'reliability']},
    'app_crash': {'title': 'Programs crashing or closing', 'checks': ['event_signals', 'updates', 'disk_health', 'security'], 'perf': True, 'default': ['reliability', 'deep_scan']},
    'overheat': {'title': 'Overheating or a loud fan', 'checks': ['event_signals', 'startup_apps'], 'perf': True, 'default': ['watch']},
    'battery': {'title': 'Battery draining fast', 'checks': ['battery', 'startup_apps', 'event_signals'], 'perf': True, 'default': ['watch', 'battery_report']},
    'network': {'title': 'Wi-Fi or internet dropping', 'checks': ['event_signals', 'updates'], 'perf': False, 'default': ['network_check', 'device_manager']},
    'general': {'title': 'Something isn’t right', 'checks': ['event_signals', 'crashes', 'disk_health', 'updates', 'pending_reboot', 'security'], 'perf': True, 'default': ['health_check', 'watch']},
}
SYMPTOMS = [
    ('network', r'\b(wi-?fi|wifi|internet|network|connection|ethernet)\b.*\b(drop\w*|disconnect\w*|keeps|cuts? out|unstable|lost|loses|losing)\b'),
    ('battery', r'\bbatter(y|ies)\b.*\b(drain\w*|dies|dying|fast|quick\w*|doesn.t last|does not last|runs? out)\b'),
    ('overheat', r'\b(overheat\w*|(gets?|getting|runs?|running|is|feels?|too|very|so)\b.{0,15}\b(hot|warm)|hot to the touch|fans?\b.*\b(loud|noisy|always|constantly|spinning|running|roaring))\b'),
    ('app_crash', r'\b(apps?|programs?|applications?|chrome|edge|firefox|games?|word|excel|outlook|teams|zoom|software)\b.*\b(crash\w*|clos\w* (by itself|on (its|their) own|suddenly)|quits?|keeps closing|not responding)\b'),
    ('crash', r'\b(blue ?screens?|bsod|crash\w*|restart\w*|reboot\w*|shut\w* (down|off)|turns? off|black screen)\b'),
    ('freeze', r'\b(freez\w*|froze|frozen|hang\w*|hung|lock\w* up|unresponsive|not responding)\b'),
]
NEXT_TESTS = {
    'watch': ('Catch it with a Performance Watch', 'Measures the processor, memory and disk for a few minutes while the problem happens, and records spikes.'),
    'deep_scan': ('Run the deep scan as administrator', 'Reads drive SMART counters, crash dumps, boot times and system-file health (one Windows permission prompt).'),
    'memory_test': ('Test the memory', 'Windows Memory Diagnostic checks the RAM for errors. It needs a restart.'),
    'reliability': ('Open Reliability Monitor', 'Windows’ day-by-day history of crashes, hangs and installs, good for spotting what started it.'),
    'health_check': ('Run the full Health Check', 'Checks storage, drivers, Windows events and performance in about a minute.'),
    'device_manager': ('Check devices and drivers', 'Lists every device and flags anything that isn’t working.'),
    'network_check': ('Check the network adapters', 'Shows each adapter’s status and connection.'),
    'battery_report': ('Check the battery', 'Battery wear, runtime and its trend.'),
}


def playbook_for(question):
    q = ' '.join(str(question or '').lower().split())
    return next((name for name, pattern in SYMPTOMS if re.search(pattern, q)), 'general')


def _finding(title, plain, tech, weight, tests, evidence):
    return {'title': title, 'plain': plain, 'tech': tech, 'weight': weight, 'tests': tests, 'evidence': evidence}


def _sig(e, key):
    s = e.get(key) if isinstance(e, dict) else None
    return s if isinstance(s, dict) else {}


def correlate(kind, r, perf=None, changes=(), deep=None):
    """Technician rules over the collected evidence. Returns findings, strongest first."""
    out = []
    e = r.get('event_signals') or {}
    crashes, disk, reboot, updates = (r.get(k) or {} for k in ('crashes', 'disk_health', 'pending_reboot', 'updates'))
    gpu = _sig(e, 'GpuResets')
    watchdog = [x for x in as_list((deep or {}).get('LiveKernelReports')) if isinstance(x, dict) and 'WATCHDOG' in str(x.get('Kind', '')).upper()]
    if gpu.get('Count') or watchdog:
        n = gpu.get('Count') or 0
        out.append(_finding('Graphics driver', f'The graphics driver stopped responding {n or len(watchdog)} time{"s" if (n or len(watchdog)) != 1 else ""} this month and Windows restarted it. That matches freezes and black screens. Install the latest driver from the graphics card or PC maker.',
                            f'Display 4101 ×{n}' + (f' · LiveKernelReports WATCHDOG ×{len(watchdog)}' if watchdog else ''), 6, ['deep_scan'] if not deep else ['device_manager'], ['event_signals'] + (['deep_scan'] if watchdog else [])))
    storage = (_sig(e, 'DiskErrors').get('Count') or 0) + (_sig(e, 'StorageResets').get('Count') or 0)
    bad_disk = [x for x in as_list(disk.get('Disks')) if isinstance(x, dict) and ((x.get('ReadErrorsUncorrected') or 0) + (x.get('WriteErrorsUncorrected') or 0) or str(x.get('Health', '')).lower() not in ('healthy', ''))]
    if storage or bad_disk:
        out.append(_finding('Drive', f'The drive stopped responding or reported errors {storage} time{"s" if storage != 1 else ""} this month. A drive that pauses makes the whole PC freeze. Back up your files; check the SSD firmware and storage driver.' if storage else
                            'The drive reports a health problem. Back up your files now.', f'disk 7/51/153 + storport 129 ×{storage}' + (f' · unhealthy: {", ".join(str(x.get("Name")) for x in bad_disk)}' if bad_disk else ''),
                            6 if bad_disk else 5, ['deep_scan'], ['event_signals', 'disk_health']))
    if _sig(e, 'FileSystem').get('Count'):
        out.append(_finding('File system', 'Windows found file-system damage on a drive. A disk check (chkdsk) at the next restart can repair it; back up first.', f'Ntfs 55 ×{_sig(e, "FileSystem")["Count"]}', 4, ['deep_scan'], ['event_signals']))
    if _sig(e, 'Hardware').get('Count'):
        out.append(_finding('Hardware errors', 'The hardware reported errors it had to correct or couldn’t. Common causes are overheating, overclocking, power, or failing memory.', f'WHEA ×{_sig(e, "Hardware")["Count"]}', 6, ['memory_test', 'watch'], ['event_signals']))
    bsod = [b for b in as_list(crashes.get('BlueScreens')) if isinstance(b, dict)]
    if bsod:
        drivers = [b['Driver']['driver'] for b in bsod if b.get('Driver')]
        names = sorted({b.get('name') or b.get('Code') for b in bsod if b.get('name') or b.get('Code')})
        out.append(_finding('Blue screens', f'{len(bsod)} blue screen{"s" if len(bsod) != 1 else ""} this month ({", ".join(names)}).' + (f' The crash dumps point to {drivers[0]}; update or roll back that driver.' if drivers else ' The crash dumps can name the driver behind them.'),
                            f'BSOD ×{len(bsod)}: {", ".join(names)}' + (f' → {", ".join(sorted(set(drivers)))}' if drivers else ''), 6 if drivers else 5, ['device_manager'] if drivers else ['deep_scan'], ['crashes']))
    hard = as_list(crashes.get('UnexpectedRestarts'))
    if hard and not bsod:
        out.append(_finding('Hard freezes or power loss', f'Windows recorded {len(hard)} unexpected restart{"s" if len(hard) != 1 else ""} with no blue screen. That happens after a hard freeze someone fixed with the power button, a power loss, or overheating.',
                            f'Kernel-Power 41 ×{len(hard)} · 6008 ×{crashes.get("DirtyShutdowns", 0)}', 4 if kind in ('freeze', 'crash') else 2, ['reliability', 'memory_test'], ['crashes']))
    thermal = _sig(e, 'Thermal')
    if thermal.get('Count', 0) >= 3 or (thermal.get('Count') and kind == 'overheat'):
        out.append(_finding('Heat or power limits', f'The processor was slowed down {thermal["Count"]} times this month ({thermal.get("Week", 0)} this week), usually because it got too hot or hit a power limit. That causes stutters and short freezes. Keep the vents clear, use it on a hard surface, and check that the fan isn’t clogged with dust.',
                            f'Kernel-Processor-Power 37 ×{thermal["Count"]} ({thermal.get("Week", 0)} in 7 d)', 5 if kind in ('overheat', 'freeze') else 3, ['watch'], ['event_signals']))
    low = _sig(e, 'LowMemory')
    mem = (perf or {}).get('memory')
    if low.get('Count') or (mem or 0) >= 85:
        out.append(_finding('Memory running out', (f'Windows ran low on memory {low["Count"]} time{"s" if low["Count"] != 1 else ""} this month. ' if low.get('Count') else '') + (f'Right now {mem:.0f}% of memory is in use. ' if mem else '') +
                            'When memory runs out, Windows pauses to move data to the much slower drive, which feels like a freeze. Close programs you aren’t using, especially browser tabs.',
                            f'Resource-Exhaustion 2004 ×{low.get("Count", 0)} · RAM {mem:.0f}%' if mem else f'Resource-Exhaustion 2004 ×{low.get("Count", 0)}', 5 if kind in ('freeze', 'general') else 3, ['watch'], ['event_signals'] + (['performance'] if mem else [])))
    hangs = _sig(e, 'AppHangs')
    top = [t for t in as_list(hangs.get('Top')) if isinstance(t, dict) and t.get('Name')]
    if hangs.get('Count', 0) >= 2 and top and top[0]['Count'] * 2 >= hangs['Count']:
        out.append(_finding('One program', f'Most of the "not responding" events ({top[0]["Count"]} of {hangs["Count"]}) are from {top[0]["Name"]}. If the freezes happen in that program, update or reinstall it.',
                            f'Application Hang 1002: {", ".join(f"{t["Name"]}×{t["Count"]}" for t in top[:3])}', 5 if kind in ('freeze', 'app_crash') else 2, ['reliability'], ['event_signals']))
    app = _sig(e, 'AppCrashes')
    if kind == 'app_crash' and app.get('Count'):
        tops = [t for t in as_list(app.get('Top')) if isinstance(t, dict) and t.get('Name')]
        out.append(_finding('Program crashes', f'{app["Count"]} program crash{"es" if app["Count"] != 1 else ""} this month' + (f', mostly {tops[0]["Name"]}' if tops and tops[0]['Count'] * 2 >= app['Count'] else '') + '. Update or reinstall the program that crashes; if many different programs crash, test the memory.',
                            f'Application Error 1000 ×{app["Count"]}' + (': ' + ', '.join(f'{t["Name"]}×{t["Count"]}' for t in tops[:3]) if tops else ''), 5, ['reliability', 'memory_test'], ['event_signals']))
    wifi = _sig(e, 'WifiDrops')
    if wifi.get('Count') and (kind == 'network' or wifi['Count'] >= 5):
        out.append(_finding('Wi-Fi', f'The Wi-Fi connection dropped {wifi["Count"]} time{"s" if wifi["Count"] != 1 else ""} this month. Update the Wi-Fi driver from the PC maker, and in Device Manager turn off "Allow the computer to turn off this device to save power" for the Wi-Fi adapter.',
                            f'WLAN-AutoConfig 8003 ×{wifi["Count"]}', 5 if kind == 'network' else 2, ['network_check', 'device_manager'], ['event_signals']))
    if kind == 'battery':
        b = r.get('battery') or {}
        if b.get('HealthPercent') is not None and b['HealthPercent'] < 70:
            out.append(_finding('Battery wear', f'The battery holds only {b["HealthPercent"]}% of its original charge, so it drains much faster than when new. A replacement battery fixes that.', f'Battery health {b["HealthPercent"]}%', 6, ['battery_report'], ['battery']))
        if (perf or {}).get('cpu', 0) >= 30:
            out.append(_finding('Busy processor', f'The processor is {perf["cpu"]:.0f}% busy while you’re not doing much, which drains the battery. A Performance Watch shows what keeps it busy.', f'CPU {perf["cpu"]:.0f}%', 4, ['watch'], ['performance']))
    if kind in ('battery', 'overheat'):
        apps = as_list((r.get('startup_apps') or {}).get('Apps'))
        if len(apps) >= 8:
            out.append(_finding('Startup apps', f'{len(apps)} apps start with Windows and keep running in the background. Turning off the ones you don’t need saves power and heat.', f'Startup entries {len(apps)}', 2, [], ['startup_apps']))
    c = next((v for v in as_list(disk.get('Volumes')) if isinstance(v, dict) and v.get('Drive') == 'C:' and v.get('SizeGB')), None)
    if c and (c.get('FreeGB') or 0) / c['SizeGB'] < 0.1:
        out.append(_finding('Low disk space', f'Drive C: has only {c.get("FreeGB")} GB free. Windows slows down and can stall when the system drive is nearly full.', f'C: {c.get("FreeGB")}/{c["SizeGB"]} GB', 3, [], ['disk_health']))
    if reboot.get('ComponentServicing') or reboot.get('WindowsUpdate') or (reboot.get('UptimeDays') or 0) >= 7:
        out.append(_finding('Restart', ('A Windows update is waiting for a restart. ' if reboot.get('ComponentServicing') or reboot.get('WindowsUpdate') else '') + f'The PC has been running for {reboot.get("UptimeDays")} days. Restart it first; it clears built-up problems and finishes updates.',
                            f'Uptime {reboot.get("UptimeDays")} d · CBS {reboot.get("ComponentServicing")} · WU {reboot.get("WindowsUpdate")}', 2, [], ['pending_reboot']))
    for item in changes or ():
        if item.get('kind') in ('crash', 'updates') and item.get('state') in ('note', 'attention', 'problem'):
            out.append(_finding('What changed', item['plain'] + ('.' if not item['plain'].endswith('.') else ''), item.get('tech', ''), 3, ['reliability'], ['timeline']))
    failures = [f for f in as_list(updates.get('Failures')) if isinstance(f, dict) and f.get('Error') not in ('0x80073D02', None)]
    if len(failures) >= 2 and kind in ('crash', 'general', 'app_crash'):
        out.append(_finding('Windows Update', f'{len(failures)} updates failed to install this month. Ask PC Medic about the error codes (Deep checks > Windows Update errors) to see why.', ', '.join(sorted({f["Error"] for f in failures})), 2, [], ['updates']))
    return sorted(out, key=lambda f: -f['weight'])


def rank_tests(kind, findings, deep=None):
    score = {}
    for f in findings:
        for i, t in enumerate(f['tests']):
            score[t] = score.get(t, 0) + f['weight'] - i
    for i, t in enumerate(PLAYBOOKS[kind]['default']):
        score.setdefault(t, 1 - i * 0.1)
    if deep:
        score.pop('deep_scan', None)  # already have one; findings would name what it showed
    return [{'id': t, 'label': NEXT_TESTS[t][0], 'why': NEXT_TESTS[t][1]} for t, _ in sorted(score.items(), key=lambda kv: -kv[1])[:3]]


def investigate(question, demo=False, kind=None):
    """Run the playbook for this problem and return evidence, findings and next tests."""
    kind = kind if kind in PLAYBOOKS else playbook_for(question)
    book = PLAYBOOKS[kind]
    import today
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {name: pool.submit(system_checks.check, name) for name in book['checks']}
        perf_job = pool.submit(today.quick_performance, demo) if book['perf'] else None
        r = {name: job.result() for name, job in jobs.items()}
        perf = perf_job.result() if perf_job else None
    try:
        import timeline
        changes = [i for i in timeline.summary().get('items') or [] if isinstance(i, dict)]
    except Exception:
        changes = []
    deep = system_checks.deep_scan()
    routines = [{'id': name, 'title': system_checks.TITLES[name].split(' (')[0], 'available': bool(d.get('available')),
                 'plain': system_checks.describe(name, d), 'technical': system_checks.describe_technical(name, d)} for name, d in r.items()]
    if perf:
        routines.append({'id': 'performance', 'title': 'Performance right now', 'available': True,
                         'plain': f'Processor {perf["cpu"]:.0f}% busy, memory {perf["memory"]:.0f}% used, drive {perf["disk"]:.0f}% busy.',
                         'technical': f'CPU {perf["cpu"]:.0f}% · RAM {perf["memory"]:.0f}% of {perf.get("total_gb")} GB · disk {perf["disk"]:.0f}% ({perf["samples"]} s)'})
    if changes:
        routines.append({'id': 'timeline', 'title': 'What changed this week', 'available': True,
                         'plain': ' '.join(i.get('plain', '') for i in changes[:4]), 'technical': ' · '.join(i.get('tech', '') for i in changes[:6])})
    if deep:
        import deep_scan
        routines.append({'id': 'deep_scan', 'title': 'Latest deep scan', 'available': True, 'plain': deep_scan.describe(deep), 'technical': deep_scan.describe(deep, True)})
    findings = correlate(kind, r, perf, changes, deep)
    tests = rank_tests(kind, findings, deep)
    return {'kind': kind, 'title': book['title'], 'question': str(question or '')[:300], 'routines': routines, 'findings': findings, 'next_tests': tests,
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'cloud': for_cloud(kind, r, perf, changes, deep, findings)}


def for_cloud(kind, r, perf, changes, deep, findings):
    """The evidence Claude may see: the minimized check data and the findings' technical lines (no program names)."""
    import deep_scan
    names = {t['Name'] for k in ('AppHangs', 'AppCrashes') for t in as_list(((r.get('event_signals') or {}).get(k) or {}).get('Top')) if isinstance(t, dict) and t.get('Name')}
    scrub = lambda text: re.sub('|'.join(re.escape(n) for n in names), '[program]', text) if names else text
    return {'playbook': kind, 'checks': {name: system_checks.for_cloud(name, d) for name, d in r.items()},
            'performance': {k: perf.get(k) for k in ('cpu', 'memory', 'disk', 'total_gb')} if perf else None,
            'changes_this_week': [{'kind': i.get('kind'), 'tech': i.get('tech')} for i in changes if i.get('kind') != 'startup'],
            'deep_scan': deep_scan.for_cloud(deep) if deep else None,
            'findings': [{'title': f['title'], 'tech': scrub(f['tech']), 'weight': f['weight'], 'suggested_tests': f['tests']} for f in findings]}


def describe(result, technical=False):
    """The investigation as text for the answer box."""
    lines = [f'Investigating: {result["title"].lower()}.', '']
    if technical:
        lines.append('What I checked:')
        lines += [f'• {r["title"]}: ' + (r['technical'] if r['available'] else 'unavailable') for r in result['routines']]
    else:
        lower = lambda t: t if t.startswith('Windows') else t[0].lower() + t[1:]
        lines.append('What I checked: ' + ', '.join(lower(r['title']) for r in result['routines'] if r['available']) + '.')
    lines += ['', 'What the evidence points to:']
    if result['findings']:
        for i, f in enumerate(result['findings'][:5], 1):
            lines.append(f'{i}. {f["title"]}: {f["tech"] if technical else f["plain"]}')
    else:
        lines.append('Nothing in the logs or checks explains it yet. The best next step is to measure the PC while it happens.')
    if result['next_tests']:
        t = result['next_tests'][0]
        lines += ['', f'Next test: {t["label"]}. {t["why"]}']
    lines += ['', 'Nothing was changed. Everything above was read on this PC.']
    return '\n'.join(lines)
