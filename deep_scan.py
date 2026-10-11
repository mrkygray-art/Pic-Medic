"""Deep scan: read-only checks that Windows only allows as administrator.

dashboard.py starts a second copy of PC Medic with "--deep-scan" through the Windows UAC prompt
(ShellExecuteEx "runas"). That copy runs only the fixed, read-only steps below, writes deep_scan.json, and
exits. It takes no instructions except where to write the result, and that file name is fixed.

Collected: drive reliability counters (SMART), boot and shutdown times with what slowed them, Windows image
health (DISM /CheckHealth, optionally sfc /verifyonly), the file-system dirty bit, BitLocker, TPM and Secure
Boot, and the crash dumps, read with bluescreen.parse_dump(). Never collected: recovery keys, user names,
file contents. App names that slowed startup stay on this PC (for_cloud drops them).
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import bluescreen

OUTPUT_NAME = 'deep_scan.json'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
HEADER = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)\n$ErrorActionPreference='SilentlyContinue'\n"

SCRIPT = r"""
$since=(Get-Date).AddDays(-30)
function EvData($e){$d=@{};([xml]$e.ToXml()).Event.EventData.Data | ForEach-Object {$d[$_.Name]=$_.'#text'};$d}
$disks=@(Get-PhysicalDisk | ForEach-Object { $r=$_ | Get-StorageReliabilityCounter
 [pscustomobject]@{Name=$_.FriendlyName;MediaType=[string]$_.MediaType;BusType=[string]$_.BusType;Health=[string]$_.HealthStatus;TemperatureC=$r.Temperature;TemperatureMaxC=$r.TemperatureMax;
  WearPercent=$r.Wear;PowerOnHours=$r.PowerOnHours;ReadErrorsTotal=$r.ReadErrorsTotal;ReadErrorsUncorrected=$r.ReadErrorsUncorrected;WriteErrorsUncorrected=$r.WriteErrorsUncorrected;StartStopCycles=$r.StartStopCycleCount} })
$log='Microsoft-Windows-Diagnostics-Performance/Operational'
$boots=@(Get-WinEvent -FilterHashtable @{LogName=$log;Id=100} -MaxEvents 10 | ForEach-Object {$d=EvData $_;[pscustomobject]@{Date=$_.TimeCreated.ToString('s');BootMs=[int]$d.BootTime;MainPathMs=[int]$d.MainPathBootTime;PostBootMs=[int]$d.BootPostBootTime}})
$shutdowns=@(Get-WinEvent -FilterHashtable @{LogName=$log;Id=200} -MaxEvents 5 | ForEach-Object {$d=EvData $_;[pscustomobject]@{Date=$_.TimeCreated.ToString('s');ShutdownMs=[int]$d.ShutdownTime}})
$kinds=@{101='App';102='Driver';103='Service';106='Background task';107='Device';108='Device';109='Device';110='Disk'}
$slow=@(Get-WinEvent -FilterHashtable @{LogName=$log;Id=101,102,103,106,107,108,109,110;StartTime=$since} -MaxEvents 60 | ForEach-Object {$d=EvData $_
 $n=@($d.FriendlyName,$d.Name,$d.FileName) | Where-Object {$_} | Select-Object -First 1
 [pscustomobject]@{Date=$_.TimeCreated.ToString('s');Kind=$kinds[$_.Id];Name=[string]$n;TotalMs=[int]$d.TotalTime;DelayMs=[int]$d.DegradationTime}})
$dirty=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {$t=(fsutil dirty query $_.DeviceID) -join ' ';[pscustomobject]@{Drive=$_.DeviceID;Dirty=($t -match 'is Dirty' -and $t -notmatch 'NOT Dirty');Text=$t.Trim()}})
$bl=@(Get-BitLockerVolume | ForEach-Object {[pscustomobject]@{Drive=$_.MountPoint;Status=[string]$_.VolumeStatus;Protection=[string]$_.ProtectionStatus;Percent=$_.EncryptionPercentage;Method=[string]$_.EncryptionMethod;Protectors=@($_.KeyProtector | ForEach-Object {[string]$_.KeyProtectorType})}})
$tpm=Get-Tpm
$sb=$null;try{$sb=Confirm-SecureBootUEFI -ErrorAction Stop}catch{}
$md=Join-Path $env:SystemRoot 'Minidump'
$dumps=@(Get-ChildItem $md -Filter *.dmp | Sort-Object LastWriteTime -Descending | Select-Object -First 10 | ForEach-Object {[pscustomobject]@{File=$_.Name;Path=$_.FullName;Date=$_.LastWriteTime.ToString('s');SizeKB=[math]::Round($_.Length/1KB)}})
$mem=Get-Item (Join-Path $env:SystemRoot 'MEMORY.DMP')
$lkr=@(Get-ChildItem (Join-Path $env:SystemRoot 'LiveKernelReports') -Recurse -Filter *.dmp | Where-Object LastWriteTime -gt $since | ForEach-Object {[pscustomobject]@{Kind=$_.Directory.Name;Date=$_.LastWriteTime.ToString('s')}})
[pscustomobject]@{Disks=$disks;Boots=$boots;Shutdowns=$shutdowns;SlowStartup=$slow;Dirty=$dirty;BitLocker=$bl
 Tpm=$(if($tpm){[pscustomobject]@{Present=$tpm.TpmPresent;Ready=$tpm.TpmReady;Enabled=$tpm.TpmEnabled;Activated=$tpm.TpmActivated}}else{$null});SecureBoot=$sb
 DumpFiles=$dumps;MemoryDump=$(if($mem){$mem.LastWriteTime.ToString('s')}else{$null});LiveKernelReports=$lkr}|ConvertTo-Json -Depth 5 -Compress
"""

DRIVER_INFO = r"""
$out=@{};foreach($n in $args){$p=Join-Path $env:SystemRoot ('System32\drivers\'+$n);$f=Get-Item $p
 if($f){$v=$f.VersionInfo;$out[$n]=[pscustomobject]@{company=[string]$v.CompanyName;version=[string]$v.FileVersion;driver_date=$f.LastWriteTime.ToString('yyyy-MM-dd');product=[string]$v.ProductName}}}
[pscustomobject]$out|ConvertTo-Json -Compress
"""


def powershell(script, args=(), timeout=180):
    p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', HEADER + script, *args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout, creationflags=NO_WINDOW)
    return json.loads(p.stdout.lstrip('﻿').strip() or 'null')


def dism_health():
    """DISM /CheckHealth: read-only, reports whether the component store is flagged as corrupted."""
    try:
        p = subprocess.run(['dism.exe', '/Online', '/Cleanup-Image', '/CheckHealth', '/English'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=300, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'state': 'error', 'text': type(exc).__name__}
    out = p.stdout
    state = ('healthy' if re.search(r'No component store corruption detected', out, re.I) else
             'repairable' if re.search(r'component store is repairable', out, re.I) else
             'not repairable' if re.search(r'not repairable', out, re.I) else 'error')
    lines = [x.strip() for x in out.splitlines() if x.strip() and not x.startswith(('Deployment Image', 'Version:', 'Image Version'))]
    return {'state': state, 'text': ' '.join(lines[-2:])[:300]}


def sfc_verify():
    """sfc /verifyonly: checks protected system files without repairing anything (several minutes). Output is UTF-16."""
    try:
        p = subprocess.run(['sfc.exe', '/verifyonly'], capture_output=True, timeout=3600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'state': 'error', 'text': type(exc).__name__}
    raw = p.stdout
    text = raw.decode('utf-16-le', errors='replace') if raw[:200].count(b'\x00') > 20 else raw.decode('utf-8', errors='replace')
    text = re.sub(r'\s+', ' ', text.replace('\x00', ''))
    state = ('healthy' if re.search(r'did not find any integrity violations', text, re.I) else
             'violations' if re.search(r'found integrity violations', text, re.I) else 'error')
    return {'state': state, 'text': text[-300:].strip()}


def analyze_dumps(files):
    """Read each minidump (administrator only) and add the likely driver's maker and version."""
    out = []
    for f in files or []:
        parsed = bluescreen.parse_dump_file(f.get('Path', '')) if isinstance(f, dict) else None
        if not parsed:
            out.append({'file': f.get('File'), 'date': f.get('Date'), 'readable': False})
            continue
        item = {'file': f.get('File'), 'date': f.get('Date'), 'readable': True, **bluescreen.explain(parsed['code'] or 0),
                'params': parsed['params'], 'driver': parsed['driver'], 'reason': parsed['reason']}
        out.append(item)
    names = sorted({x['driver'] for x in out if x.get('driver')})
    if names:
        try:
            info = powershell(DRIVER_INFO, names, timeout=60) or {}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            info = {}
        for x in out:
            meta = info.get(x.get('driver') or '') if isinstance(info, dict) else None
            if isinstance(meta, dict):
                x.update({k: meta.get(k) or None for k in ('company', 'version', 'driver_date', 'product')})
    return out


def run(include_sfc=False):
    started = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        data = powershell(SCRIPT) or {}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        data = {'error': type(exc).__name__}
    data['Dism'] = dism_health()
    if include_sfc:
        data['Sfc'] = sfc_verify()
    data['Dumps'] = analyze_dumps(data.pop('DumpFiles', None) if isinstance(data.get('DumpFiles'), list) else
                                  [data.pop('DumpFiles')] if isinstance(data.get('DumpFiles'), dict) else [])
    data.update(started=started, finished=datetime.now(timezone.utc).isoformat(timespec='seconds'), sfc=include_sfc)
    return data


def safe_output(path):
    """Only ever write a file named deep_scan.json, and never through a link: this process runs as administrator."""
    p = Path(path)
    if p.name != OUTPUT_NAME or not p.parent.is_dir() or p.is_symlink() or p.parent.is_symlink():
        raise SystemExit('Refusing to write the deep scan there.')
    return p


def write(path, data):
    tmp = path.with_name(OUTPUT_NAME + '.tmp')
    tmp.write_text(json.dumps(data, default=str), encoding='utf-8')
    os.replace(tmp, path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = safe_output(argv[argv.index('--output') + 1]) if '--output' in argv else None
    if out is None:
        raise SystemExit('--output is required')
    write(out, {'running': True, 'started': datetime.now(timezone.utc).isoformat(timespec='seconds')})
    try:
        write(out, run('--sfc' in argv))
    except Exception as exc:  # leave a readable failure instead of a scan that never finishes
        write(out, {'error': f'The deep scan stopped: {type(exc).__name__}', 'finished': datetime.now(timezone.utc).isoformat(timespec='seconds')})


# ---------------- reading the result ----------------
def _ms(v):
    return f'{v / 1000:.0f} s' if isinstance(v, (int, float)) and v else '?'


def items(d):
    """Rows for the page: {'area','state','plain','tech'}, like system_checks.security_items."""
    out = []
    row = lambda area, state, plain, tech: out.append({'area': area, 'state': state, 'plain': plain, 'tech': tech})
    for disk in d.get('Disks') or []:
        if not isinstance(disk, dict):
            continue
        errors = (disk.get('ReadErrorsUncorrected') or 0) + (disk.get('WriteErrorsUncorrected') or 0)
        wear = disk.get('WearPercent')
        state = 'problem' if errors or str(disk.get('Health')).lower() not in ('healthy', '') else 'attention' if (wear or 0) >= 80 else 'note' if (wear or 0) >= 50 else 'good'
        bits = [f'{wear}% worn' if wear is not None else '', f'{disk["TemperatureC"]}°C' if disk.get('TemperatureC') else '', f'{disk["PowerOnHours"]:,} hours powered on' if disk.get('PowerOnHours') else '']
        row('Drive', state, f'{disk.get("Name")}: ' + ('reports uncorrected errors. Back up your files now and plan to replace it.' if errors else
                                                       'reports a health problem. Back up your files now.' if state == 'problem' else
                                                       'healthy' + (f' ({", ".join(b for b in bits if b)})' if any(bits) else '') + '.'),
            f'{disk.get("Name")} · {disk.get("MediaType")} {disk.get("BusType")} · {disk.get("Health")} · wear {wear} · {disk.get("TemperatureC")}°C (max {disk.get("TemperatureMaxC")}) · POH {disk.get("PowerOnHours")} · read err total {disk.get("ReadErrorsTotal")} · uncorrected R/W {disk.get("ReadErrorsUncorrected")}/{disk.get("WriteErrorsUncorrected")}')
    boots = [b for b in d.get('Boots') or [] if isinstance(b, dict) and b.get('BootMs')]
    if boots:
        last, avg = boots[0], sum(b['BootMs'] for b in boots) / len(boots)
        slow = [s for s in d.get('SlowStartup') or [] if isinstance(s, dict) and s.get('DelayMs')]
        worst = sorted({(s['Kind'], s['Name']): s for s in slow}.values(), key=lambda s: -s['DelayMs'])[:3]
        state = 'attention' if last['BootMs'] > 120000 else 'note' if last['BootMs'] > 60000 else 'good'
        row('Startup time', state, f'The last startup took about {_ms(last["BootMs"])} (average {_ms(avg)} over the last {len(boots)}).' +
            (' Slowing it down: ' + ', '.join(f'{s["Name"]} ({_ms(s["DelayMs"])} extra)' for s in worst) + '.' if worst else ''),
            f'Boot {last["BootMs"]} ms (main path {last.get("MainPathMs")}, post-boot {last.get("PostBootMs")}) · avg {avg:.0f} ms/{len(boots)}' +
            ''.join(f' · {s["Kind"]} {s["Name"]} +{s["DelayMs"]} ms' for s in worst))
    shut = [s for s in d.get('Shutdowns') or [] if isinstance(s, dict) and s.get('ShutdownMs')]
    if shut:
        row('Shutdown time', 'note' if shut[0]['ShutdownMs'] > 60000 else 'good', f'The last shutdown took about {_ms(shut[0]["ShutdownMs"])}.', f'Shutdown {shut[0]["ShutdownMs"]} ms')
    dism = d.get('Dism') or {}
    if dism:
        state = {'healthy': 'good', 'repairable': 'attention', 'not repairable': 'problem'}.get(dism.get('state'), 'note')
        row('Windows image', state, {'healthy': 'Windows’ own system files show no damage (DISM).',
                                     'repairable': 'Windows found damaged system files it can repair. A technician can run DISM /RestoreHealth, then sfc /scannow.',
                                     'not repairable': 'Windows found system file damage it can’t repair by itself. A repair install of Windows may be needed.'}.get(dism.get('state'), 'The Windows image check didn’t finish.'),
            f'DISM /CheckHealth: {dism.get("state")} · {dism.get("text")}')
    sfc = d.get('Sfc')
    if sfc:
        row('System files', {'healthy': 'good', 'violations': 'attention'}.get(sfc.get('state'), 'note'),
            {'healthy': 'System File Checker found no problems.', 'violations': 'System File Checker found damaged system files. A technician can run sfc /scannow to repair them.'}.get(sfc.get('state'), 'System File Checker didn’t finish.'),
            f'sfc /verifyonly: {sfc.get("state")} · {sfc.get("text")}')
    checked = [x for x in d.get('Dirty') or [] if isinstance(x, dict) and re.search(r'is (NOT )?Dirty', x.get('Text') or '', re.I)]
    dirty = [x['Drive'] for x in checked if x.get('Dirty')]
    if checked:
        row('File system', 'attention' if dirty else 'good', f'Windows has flagged {", ".join(dirty)} for a disk check at the next restart.' if dirty else 'No drive is flagged for a disk check.',
            'fsutil dirty: ' + ' · '.join(f'{x.get("Drive")} {"DIRTY" if x.get("Dirty") else "clean"}' for x in checked))
    for v in d.get('BitLocker') or []:
        if not isinstance(v, dict) or not v.get('Drive'):
            continue
        on = str(v.get('Protection')).lower() == 'on'
        recovery = 'RecoveryPassword' in (v.get('Protectors') or [])
        row('BitLocker', 'good' if on and recovery else 'note' if on else 'note',
            f'{v["Drive"]} is encrypted' + (' and has a recovery key. Make sure that key is saved in your Microsoft account or printed.' if recovery else ' but has no recovery key protector.') if on else f'{v["Drive"]} isn’t protected by BitLocker.',
            f'{v["Drive"]} {v.get("Status")} · protection {v.get("Protection")} · {v.get("Percent")}% · {v.get("Method")} · protectors {", ".join(v.get("Protectors") or []) or "none"}')
    tpm = d.get('Tpm')
    if isinstance(tpm, dict) and tpm.get('Present') is not None:  # Get-Tpm answers only as administrator
        row('TPM', 'good' if tpm.get('Present') and tpm.get('Ready') else 'attention', 'The TPM is present and ready.' if tpm.get('Present') and tpm.get('Ready') else 'The TPM isn’t ready. Check it in the UEFI (BIOS) settings or tpm.msc.',
            f'TpmPresent {tpm.get("Present")} · Ready {tpm.get("Ready")} · Enabled {tpm.get("Enabled")} · Activated {tpm.get("Activated")}')
    dumps = [x for x in d.get('Dumps') or [] if isinstance(x, dict)]
    for x in dumps[:5]:
        if not x.get('readable'):
            row('Crash dump', 'note', f'{x.get("file")} couldn’t be read.', f'{x.get("file")} unreadable')
            continue
        who = f' Likely cause: {x["driver"]}' + (f' ({x["company"]}' + (f', version {x["version"]}' if x.get('version') else '') + ')' if x.get('company') else '') + '.' if x.get('driver') else ' PC Medic couldn’t tell which driver caused it.'
        row('Crash dump', 'attention', f'{str(x.get("date"))[:10]}: {x.get("name")} ({x.get("code")}). {x.get("meaning")}{who}',
            f'{x.get("file")} · {x.get("code")} {x.get("name")} · P1-4 {", ".join(x.get("params") or [])} · driver {x.get("driver") or "?"} ({x.get("reason") or "-"})' +
            (f' · {x.get("company")} {x.get("version")} ({x.get("driver_date")})' if x.get('company') else ''))
    if not dumps:
        row('Crash dumps', 'good', 'No crash dump files are saved on this PC.', 'Minidump: 0 files' + (f' · MEMORY.DMP {d["MemoryDump"][:10]}' if d.get('MemoryDump') else ''))
    lkr = [x for x in d.get('LiveKernelReports') or [] if isinstance(x, dict)]
    if lkr:
        kinds = sorted({x.get('Kind') for x in lkr if x.get('Kind')})
        row('Hidden hangs', 'note', f'Windows recovered from {len(lkr)} serious hang{"s" if len(lkr) != 1 else ""} this month without a blue screen ({", ".join(kinds)}). Graphics (WATCHDOG) entries usually mean the graphics driver.',
            f'LiveKernelReports 30 d: {len(lkr)} · ' + ', '.join(kinds))
    return out


def describe(d, technical=False):
    if not d:
        return 'No deep scan has been run on this PC yet.'
    if d.get('error'):
        return d['error']
    rows = items(d)
    when = str(d.get('finished', ''))[:16].replace('T', ' ')
    if technical:
        return f'Deep scan ({when} UTC): ' + ' | '.join(f'{r["area"]} [{r["state"]}] {r["tech"]}' for r in rows)
    bad = [r for r in rows if r['state'] in ('attention', 'problem')]
    head = f'Deep scan ({when} UTC): ' + ('nothing serious found.' if not bad else f'{len(bad)} thing{"s" if len(bad) != 1 else ""} need{"" if len(bad) != 1 else "s"} attention.')
    return '\n'.join([head] + [('✓ ' if r['state'] == 'good' else '• ') + r['plain'] for r in sorted(rows, key=lambda r: r['state'] == 'good')])


def for_cloud(d):
    """What Claude may see: no app or service names from slow startups, no dump file paths."""
    if not d:
        return {'available': False}
    keep = {k: d.get(k) for k in ('Disks', 'Boots', 'Shutdowns', 'Dirty', 'Tpm', 'SecureBoot', 'Dism', 'Sfc', 'finished')}
    keep['SlowStartupCount'] = len(d.get('SlowStartup') or [])
    keep['BitLocker'] = [{k: v.get(k) for k in ('Drive', 'Protection', 'Percent', 'Protectors')} for v in d.get('BitLocker') or [] if isinstance(v, dict)]
    keep['Dumps'] = [{k: x.get(k) for k in ('date', 'code', 'name', 'driver', 'company', 'version')} for x in d.get('Dumps') or [] if isinstance(x, dict)]
    keep['LiveKernelReports'] = sorted({x.get('Kind') for x in d.get('LiveKernelReports') or [] if isinstance(x, dict)})
    return keep


if __name__ == '__main__':
    main()
