"""Guided troubleshooting: understand -> investigate -> explain -> recommend -> validate -> save.

A case walks one problem ("my computer is slow") through those steps. PC Medic only measures and explains;
the user makes every change, guided step by step, and PC Medic re-measures to check the result.
Cases are saved on this PC (cases.json); process and app names stay local.
"""
import json
import re
import secrets
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import system_checks
from performance_diagnostics import collect_performance

CASES_FILE = None  # set by dashboard.py
LOCK = threading.Lock()
MAX_CASES = 50

CONTEXTS = {
    'startup': 'When the computer starts up',
    'browsing': 'While browsing the web',
    'gaming': 'While gaming',
    'always': 'All the time',
    'unsure': 'Not sure',
}
QUESTION = {'text': 'When does your computer feel slow?', 'options': CONTEXTS}

# Windows parts that cause background activity but should not be closed.
SYSTEM_PROCESSES = {'system', 'registry', 'memory compression', 'svchost', 'msmpeng', 'searchindexer', 'tiworker', 'trustedinstaller',
                    'wuauclt', 'msedgewebview2', 'dwm', 'csrss', 'lsass', 'services', 'wininit', 'winlogon', 'smss', 'explorer',
                    'audiodg', 'mpdefendercoreservice', 'nissrv', 'sgrmbroker', 'spoolsv', 'fontdrvhost', 'ctfmon', 'runtimebroker',
                    'searchhost', 'startmenuexperiencehost', 'shellexperiencehost', 'sihost', 'taskhostw', 'wmiprvse', 'powershell',
                    'python', 'pythonw', 'conhost', 'onedrive'}
BACKGROUND_TASKS = {'msmpeng': 'Microsoft Defender (antivirus scan)', 'searchindexer': 'Windows Search indexing',
                    'tiworker': 'Windows Update installing', 'trustedinstaller': 'Windows Update installing',
                    'onedrive': 'OneDrive syncing', 'wuauclt': 'Windows Update', 'mpdefendercoreservice': 'Microsoft Defender'}
BROWSERS = {'chrome': 'Chrome', 'msedge': 'Edge', 'firefox': 'Firefox', 'brave': 'Brave', 'opera': 'Opera', 'vivaldi': 'Vivaldi'}
# Startup apps most people do not need at sign-in (they open fine when started by hand).
USUALLY_OPTIONAL = re.compile(r'steam|epic|discord|spotify|plarium|skype|zoom|teams|edgeautolaunch|battle\.?net|eadesktop|origin|ubisoft|'
                              r'utorrent|qbittorrent|ccleaner|itunes|adobe.*(update|arm)|acrotray|googleupdate|opera|vivaldi|whatsapp|telegram', re.I)
KEEP_AT_STARTUP = re.compile(r'securityhealth|defender|rtk|realtek|audio|nvidia|igfx|intel|amd|radeon|synaptics|elan|touchpad|onedrive|'
                             r'dropbox|googledrive|bitdefender|norton|mcafee|avast|avg|kaspersky|eset|malwarebytes', re.I)

PROCESS_SCRIPT = r'''
$n=(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
$p=@(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | Where-Object { $_.Name -notin '_Total','Idle' } | ForEach-Object {
 [pscustomobject]@{Name=($_.Name -replace '#\d+$','');Cpu=[double]$_.PercentProcessorTime;Io=[double]$_.IODataBytesPersec;Ram=[double]$_.WorkingSetPrivate}})
[pscustomobject]@{Cores=$n;Processes=$p}|ConvertTo-Json -Depth 3 -Compress
'''

# Startup apps and whether each is turned on (StartupApproved: an odd first byte means turned off).
STARTUP_SCRIPT = r'''
$keys=@('HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32','HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder',
 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder')
function Get-State($names){ foreach($k in $keys){ foreach($n in $names){ $v=(Get-ItemProperty -Path $k -Name $n).$n; if($v){ if(($v[0] % 2) -eq 1){return 'off'}else{return 'on'} } } }; 'on' }
$apps=@(Get-CimInstance Win32_StartupCommand | ForEach-Object { $file=Split-Path ($_.Command -replace '"','') -Leaf
 [pscustomobject]@{Name=$_.Name;State=(Get-State @($_.Name,($_.Name+'.lnk'),$file))} } | Sort-Object Name -Unique)
[pscustomobject]@{Apps=$apps}|ConvertTo-Json -Depth 3 -Compress
'''

POWER_SCRIPT = r'''
$plan=(powercfg /getactivescheme) -replace '.*\((.*)\).*','$1'
$b=@(Get-CimInstance Win32_Battery)
[pscustomobject]@{Plan=$plan;HasBattery=($b.Count -gt 0);OnBattery=($b.Count -gt 0 -and $b[0].BatteryStatus -eq 1)}|ConvertTo-Json -Compress
'''


# ---------------- measuring ----------------
def process_activity():
    data = system_checks.run(PROCESS_SCRIPT, 40)
    if not data.get('available'):
        return []
    cores = data.get('Cores') or 1
    totals = {}
    for p in system_checks.as_list(data.get('Processes')):
        name = str(p.get('Name') or '').strip()
        if not name:
            continue
        t = totals.setdefault(name.lower(), {'name': name, 'cpu': 0.0, 'io': 0.0, 'ram': 0.0, 'count': 0})
        t['cpu'] += (p.get('Cpu') or 0) / cores
        t['io'] += p.get('Io') or 0
        t['ram'] += p.get('Ram') or 0
        t['count'] += 1
    return [dict(v, cpu=round(v['cpu'], 1), ram_gb=round(v['ram'] / 1073741824, 2), io_mb_s=round(v['io'] / 1048576, 2)) for v in totals.values()]


def startup_apps():
    data = system_checks.run(STARTUP_SCRIPT, 30)
    apps = system_checks.as_list(data.get('Apps')) if data.get('available') else []
    return [{'name': re.sub(r'_[0-9A-F]{32}$', '', str(a.get('Name') or '')), 'raw': a.get('Name'), 'on': a.get('State') != 'off'} for a in apps]


def power_state():
    data = system_checks.run(POWER_SCRIPT, 20)
    return data if data.get('available') else {}


def measure(context, demo=False, seconds=5):
    """A few seconds of CPU/memory/disk samples plus the evidence the context needs."""
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {'processes': pool.submit(process_activity), 'startup': pool.submit(startup_apps),
                'disk': pool.submit(system_checks.check, 'disk_health'), 'reboot': pool.submit(system_checks.check, 'pending_reboot')}
        if context in ('gaming', 'always', 'unsure'):
            jobs['power'] = pool.submit(power_state)
        samples = []
        for _ in range(seconds):
            try:
                samples.append(collect_performance(demo=demo))
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                pass
        out = {name: job.result() for name, job in jobs.items()}
    def avg(key):
        values = [s[key] for s in samples if isinstance(s.get(key), (int, float))]
        return round(sum(values) / len(values), 1) if values else None
    total_mb = next((s.get('memory_total_mb') for s in samples if s.get('memory_total_mb')), None)
    out.update(cpu=avg('cpu_percent'), memory=avg('memory_used_percent'), disk_busy=avg('disk_busy_percent'),
               memory_total_gb=round(total_mb / 1024, 1) if total_mb else None, samples=len(samples),
               at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    return out


# ---------------- explaining ----------------
def _top(processes, key, n=3, user_apps_only=False):
    items = [p for p in processes if p[key] > 0 and (not user_apps_only or p['name'].lower() not in SYSTEM_PROCESSES)]
    return sorted(items, key=lambda p: p[key], reverse=True)[:n]


def _names(items):
    names = [p['name'] for p in items]
    return ', '.join(names[:-1]) + (' and ' + names[-1] if len(names) > 1 else names[0] if names else '')


def findings(m, context):
    """Plain-English evidence, each tied to a recommended action. Ordered by what matters most for the context."""
    out = []
    procs = m.get('processes') or []
    total_io = sum(p['io'] for p in procs) or 0
    # Memory
    if (m.get('memory') or 0) >= 85:
        top = _top(procs, 'ram_gb', 3, user_apps_only=True)
        detail = f" The most memory goes to {_names(top)} ({', '.join(str(p['ram_gb']) + ' GB' for p in top)})." if top else ''
        total = f" of {m['memory_total_gb']} GB" if m.get('memory_total_gb') else ''
        out.append({'id': 'memory', 'weight': 3, 'text': f"Memory is {m['memory']:.0f}% used{total}, leaving little room; Windows may start moving data to the much slower disk.{detail}",
                    'action': 'browser_memory' if top and top[0]['name'].lower() in BROWSERS else 'close_app', 'target': top[0]['name'] if top else None})
    # Browser memory (browsing context)
    browsers = [p for p in procs if p['name'].lower() in BROWSERS]
    if browsers:
        b = max(browsers, key=lambda p: p['ram_gb'])
        share = 100 * b['ram_gb'] / m['memory_total_gb'] if m.get('memory_total_gb') else 0
        if b['ram_gb'] >= 2.5 or share >= 25 or (context == 'browsing' and b['ram_gb'] >= 1.5):
            out.append({'id': 'browser', 'weight': 3 if context == 'browsing' else 1,
                        'text': f"{BROWSERS[b['name'].lower()]} is using {b['ram_gb']} GB of memory across {b['count']} processes (tabs and extensions each run separately).",
                        'action': 'browser_memory', 'target': b['name']})
    # Processor
    if (m.get('cpu') or 0) >= 60:
        top = _top(procs, 'cpu', 3)
        lead = top[0] if top else None
        background = lead and lead['name'].lower() in BACKGROUND_TASKS
        out.append({'id': 'cpu', 'weight': 3, 'text': f"The processor is {m['cpu']:.0f}% busy" + (f"; {_names(top)} use the most ({', '.join(str(p['cpu']) + '%' for p in top)})." if top else '.'),
                    'action': 'background_task' if background else 'close_app', 'target': lead['name'] if lead else None})
    # Disk activity
    if (m.get('disk_busy') or 0) >= 50:
        top = _top(procs, 'io', 3)
        share = round(100 * sum(p['io'] for p in top) / total_io) if total_io else 0
        lead = top[0] if top else None
        out.append({'id': 'disk', 'weight': 3 if context == 'startup' else 2,
                    'text': f"The disk is busy {m['disk_busy']:.0f}% of the time" + (f"; {_names(top)} account for {share}% of the disk activity." if top else '.'),
                    'action': 'background_task' if lead and lead['name'].lower() in BACKGROUND_TASKS else 'close_app', 'target': lead['name'] if lead else None})
    # Startup apps
    on = [a for a in (m.get('startup') or []) if a['on']]
    optional = [a for a in on if USUALLY_OPTIONAL.search(a['name']) and not KEEP_AT_STARTUP.search(a['name'])]
    if on and (len(on) >= 6 or (context == 'startup' and optional) or len(optional) >= 2):
        out.append({'id': 'startup', 'weight': 4 if context == 'startup' else 1,
                    'text': f"{len(on)} apps start automatically when you sign in" + (f"; {len(optional)} of them usually are not needed right away ({', '.join(a['name'] for a in optional[:4])})." if optional else '.'),
                    'action': 'disable_startup', 'target': (optional or on)[0]['name']})
    # Restart
    reboot = m.get('reboot') or {}
    days = reboot.get('UptimeDays') or 0
    pending = reboot.get('ComponentServicing') or reboot.get('WindowsUpdate')
    if days >= 5 or pending:
        out.append({'id': 'restart', 'weight': 2, 'text': ('A Windows update is waiting for a restart. ' if pending else '') + f"The computer has been running for {days:.0f} days since the last restart.",
                    'action': 'restart', 'target': None})
    # Free space and drive type
    for v in system_checks.as_list((m.get('disk') or {}).get('Volumes')):
        if v.get('Drive') == 'C:' and v.get('SizeGB'):
            free, size = v.get('FreeGB') or 0, v['SizeGB']
            if free < 15 or free / size < 0.1:
                out.append({'id': 'space', 'weight': 2, 'text': f"Drive C: has only {free:.0f} GB free of {size:.0f} GB; Windows slows down when the system drive is nearly full.",
                            'action': 'free_space', 'target': None})
    hdd = [d for d in system_checks.as_list((m.get('disk') or {}).get('Disks')) if str(d.get('MediaType')).upper() == 'HDD']
    if hdd:
        out.append({'id': 'hdd', 'weight': 2 if context in ('startup', 'always') else 1,
                    'text': f"{hdd[0].get('Name')} is a spinning hard drive. Hard drives are much slower than SSDs, especially at startup.", 'action': 'ssd_upgrade', 'target': None})
    # Power (gaming / all the time)
    power = m.get('power') or {}
    plan = str(power.get('Plan') or '')
    if power.get('OnBattery') or re.search(r'saver|economy', plan, re.I):
        out.append({'id': 'power', 'weight': 4 if context == 'gaming' else 2,
                    'text': ('The laptop is running on battery, which limits speed to save power. ' if power.get('OnBattery') else '') + (f"The power plan is \"{plan}\"." if plan else ''),
                    'action': 'power_mode', 'target': None})
    return sorted(out, key=lambda f: f['weight'], reverse=True)


# ---------------- recommending ----------------
def action_plan(finding):
    """Step-by-step guidance for one finding. PC Medic opens the right page; the user makes the change."""
    target = finding.get('target') or 'the app'
    plans = {
        'disable_startup': {'title': f'Turn off {target} at startup',
                            'why': 'Every app that starts at sign-in competes for the disk and processor while Windows is still loading.',
                            'steps': ['Click "Open Startup apps" below.', f'Find {target} in the list.', 'Switch it to Off. The app still works when you open it yourself.', 'Come back here and click "I\'ve done it".'],
                            'tool': 'startup', 'tool_label': 'Open Startup apps'},
        'restart': {'title': 'Restart the computer', 'why': 'A restart finishes pending updates and clears memory that apps have built up over days.',
                    'steps': ['Save your work and close your apps.', 'Open Start, click the power icon, then choose Restart (not Shut down).', 'After signing back in, open PC Medic and click "I\'ve done it".'],
                    'tool': None},
        'browser_memory': {'title': f'Reduce {BROWSERS.get(str(target).lower(), target)} memory use',
                           'why': 'Each open tab and extension uses its own memory. Closing what you are not using frees it immediately.',
                           'steps': ['Close tabs you are not using (you can bookmark them first).', 'Open the browser menu > Extensions and turn off any you do not recognize or use.',
                                     'Turn on the browser\'s memory saver: Edge "Efficiency mode" / Chrome "Memory Saver" in Settings > Performance.', 'Click "I\'ve done it" here.'],
                           'tool': None},
        'close_app': {'title': f'Close {target} if you are not using it',
                      'why': f'{target} is using a large share of the computer\'s resources right now.',
                      'steps': ['Click "Open Task Manager" below.', f'Find {target} under Processes.', 'If you are not using it, close the app normally (or select it and click End task). Save your work first.', 'Click "I\'ve done it" here.'],
                      'tool': 'task-manager', 'tool_label': 'Open Task Manager'},
        'background_task': {'title': f'Let {BACKGROUND_TASKS.get(str(target).lower(), target)} finish',
                            'why': 'This is Windows doing necessary background work. It is busy for a while and then stops on its own.',
                            'steps': ['Leave the computer on and plugged in for 15-30 minutes.', 'Avoid heavy tasks meanwhile.', 'Click "I\'ve done it" and PC Medic will measure again.'],
                            'tool': None},
        'free_space': {'title': 'Free up space on drive C:', 'why': 'Windows needs free space for updates, temporary files and memory swapping.',
                       'steps': ['Open Storage Explorer in PC Medic to find your largest files.', 'Or click "Open Storage settings" and use Cleanup recommendations / Temporary files.', 'Move or delete what you no longer need.', 'Click "I\'ve done it" here.'],
                       'tool': 'storage-settings', 'tool_label': 'Open Storage settings'},
        'ssd_upgrade': {'title': 'Consider replacing the hard drive with an SSD',
                        'why': 'Moving Windows to an SSD is usually the biggest single speed-up for an older computer.',
                        'steps': ['Ask PC Medic "Can I upgrade my SSD?" to see what fits this computer.', 'A technician or a cloning tool can move Windows to the new drive.'],
                        'tool': None, 'no_validation': True},
        'power_mode': {'title': 'Plug in and switch to best performance',
                       'why': 'On battery or a power-saving plan, Windows slows the processor and graphics to save energy.',
                       'steps': ['Plug in the charger.', 'Click "Open Power settings" below.', 'Set Power mode to "Best performance".', 'Click "I\'ve done it" here.'],
                       'tool': 'power', 'tool_label': 'Open Power settings'},
        'performance_watch': {'title': 'Measure while it is slow', 'why': 'Nothing stands out right now; slowness that comes and goes has to be caught in the act.',
                              'steps': ['When the computer feels slow, open the Performance tab.', 'Start a Performance Watch and keep working normally.', 'PC Medic records what was busy at that moment.'],
                              'tool': None, 'no_validation': True},
    }
    return dict(plans[finding['action']], action=finding['action'], target=finding.get('target'), finding=finding['id'])


# ---------------- validating ----------------
def compare(case):
    """Before/after for the recommended action, in plain English."""
    before, after, rec = case['baseline'], case['after'], case['recommendation']
    lines = []
    def change(label, key, unit='%'):
        b, a = before.get(key), after.get(key)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            lines.append(f'{label}: {b:.0f}{unit} before, {a:.0f}{unit} now.')
    if rec['action'] == 'disable_startup':
        target = str(rec.get('target') or '').lower()
        still_on = [x for x in after.get('startup') or [] if x['on'] and x['name'].lower() == target]
        count = lambda m: len([x for x in m.get('startup') or [] if x['on']])
        lines.append(f"{rec['target']} is {'still turned on' if still_on else 'now turned off'} at startup. Startup apps turned on: {count(before)} before, {count(after)} now.")
        lines.append('The real test is your next restart: notice whether signing in feels quicker.')
    elif rec['action'] == 'restart':
        b, a = (before.get('reboot') or {}).get('UptimeDays'), (after.get('reboot') or {}).get('UptimeDays')
        restarted = isinstance(a, (int, float)) and isinstance(b, (int, float)) and a < b
        lines.append('The computer has been restarted since the first check.' if restarted else 'PC Medic does not see a restart yet. Restart, then click "I\'ve done it" again.')
    elif rec['action'] == 'free_space':
        f = lambda m: next((v.get('FreeGB') for v in system_checks.as_list((m.get('disk') or {}).get('Volumes')) if v.get('Drive') == 'C:'), None)
        if f(before) is not None and f(after) is not None:
            lines.append(f'Free space on C:: {f(before):.0f} GB before, {f(after):.0f} GB now.')
    if rec['action'] in ('browser_memory', 'close_app', 'background_task', 'restart', 'power_mode', 'disable_startup'):
        change('Memory in use', 'memory')
        change('Processor busy', 'cpu')
        change('Disk busy', 'disk_busy')
    if rec['action'] == 'power_mode':
        p = after.get('power') or {}
        lines.append(('Still on battery. ' if p.get('OnBattery') else 'Plugged in. ') + (f"Power plan: {p.get('Plan')}." if p.get('Plan') else ''))
    lines.append('A few seconds of measurement cannot prove everything, so your own impression counts most.')
    return lines


# ---------------- cases ----------------
def _load():
    try:
        return json.loads(Path(CASES_FILE).read_text(encoding='utf-8')) if CASES_FILE and Path(CASES_FILE).exists() else []
    except (OSError, ValueError):
        return []


def _save(cases):
    if not CASES_FILE:
        return
    temp = Path(CASES_FILE).with_suffix('.tmp')
    temp.write_text(json.dumps(cases[-MAX_CASES:], indent=1, default=str), encoding='utf-8')
    temp.replace(CASES_FILE)


def _store(case):
    with LOCK:
        cases = [c for c in _load() if c['id'] != case['id']]
        cases.append(case)
        _save(cases)
    return case


def get(case_id):
    return next((c for c in _load() if c['id'] == case_id), None)


def public(case):
    """The case for the page: evidence and guidance, without bulky raw measurements."""
    keep = ('id', 'problem', 'context', 'status', 'question', 'explanation', 'measured', 'recommendation', 'validation', 'feeling', 'outcome', 'next', 'created', 'updated', 'tried')
    return {k: case.get(k) for k in keep}


def start(problem):
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    case = {'id': secrets.token_urlsafe(9), 'problem': str(problem)[:300], 'kind': 'slow', 'status': 'asking', 'question': QUESTION,
            'created': now, 'updated': now, 'tried': []}
    return _store(case)


def _recommend(case):
    remaining = [f for f in case['findings'] if f['action'] not in case['tried']]
    if not remaining:
        return action_plan({'action': 'performance_watch', 'id': 'none'})
    return action_plan(remaining[0])


def investigate(case_id, context, demo=False):
    case = get(case_id)
    if not case:
        raise ValueError('This troubleshooting case no longer exists. Start again.')
    if context not in CONTEXTS:
        raise ValueError('Unknown answer')
    m = measure(context, demo)
    found = findings(m, context)
    summary = f"Measured for {m['samples']} seconds: processor {m['cpu'] or 0:.0f}% busy, memory {m['memory'] or 0:.0f}% used, disk {m['disk_busy'] or 0:.0f}% busy."
    case.update(context=context, baseline=m, findings=found, status='recommended', question=None,
                explanation=[f['text'] for f in found[:3]] or ['Nothing stands out right now.'], measured=summary,
                updated=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    case['recommendation'] = _recommend(case)
    return _store(case)


def next_recommendation(case_id):
    case = get(case_id)
    if not case or not case.get('recommendation'):
        raise ValueError('This troubleshooting case no longer exists. Start again.')
    case['tried'].append(case['recommendation']['action'])
    case['recommendation'] = _recommend(case)
    case['status'], case['validation'] = 'recommended', None
    return _store(case)


def validate(case_id, demo=False):
    case = get(case_id)
    if not case or not case.get('recommendation'):
        raise ValueError('This troubleshooting case no longer exists. Start again.')
    case['after'] = measure(case.get('context') or 'always', demo)
    case['validation'] = compare(case)
    case['status'] = 'validating'
    case['updated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return _store(case)


def feedback(case_id, feeling):
    case = get(case_id)
    if not case:
        raise ValueError('This troubleshooting case no longer exists. Start again.')
    if feeling not in ('better', 'little', 'same'):
        raise ValueError('Unknown answer')
    action = (case.get('recommendation') or {}).get('title', 'the suggested change')
    case['feeling'] = feeling
    case['status'] = {'better': 'resolved', 'little': 'improved', 'same': 'not_resolved'}[feeling]
    case['outcome'] = {'better': f'Fixed: "{action}" made the computer feel faster.',
                       'little': f'Improved a little after "{action}".',
                       'same': f'"{action}" did not help.'}[feeling]
    case['tried'].append(case['recommendation']['action'])
    case['updated'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if feeling != 'better':
        case['next'] = _recommend(case)
    return _store(case)


def history(limit=20):
    return [{'id': c['id'], 'problem': c['problem'], 'context': CONTEXTS.get(c.get('context'), ''), 'status': c['status'],
             'outcome': c.get('outcome'), 'updated': c.get('updated')} for c in reversed(_load())][:limit]
