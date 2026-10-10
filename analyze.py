"""PC Medic AI V1.1: offline, read-only rule-based diagnostic interpretation."""
import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from event_log_analyzer import summarize_events


def records(value):
    return value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])


def analyze(report):
    findings = []
    def add(level, title, evidence, next_step):
        findings.append(dict(severity=level, title=title, evidence=evidence, recommended_next_step=next_step))
    checks = report.get('checks', {})
    for key, item in checks.items():
        if item.get('status') != 'ok' or item.get('data') is None:
            add('unknown', f'{key}: data unavailable', item.get('reason', 'No usable data returned'), 'Re-run collection and verify Windows permissions.')
    memory = checks.get('memory', {}).get('data')
    if isinstance(memory, dict):
        try:
            total, free = float(memory['TotalGB']), float(memory['FreeGB'])
            if total > 0:
                used_pct = 100 * (total-free)/total
                if used_pct >= 90:
                    add('warning', 'Low available physical memory', f'{used_pct:.1f}% of {total:.1f} GB in use at scan time', 'Inspect memory usage by process and repeat under typical workload.')
                elif used_pct >= 80:
                    add('info', 'Elevated memory usage', f'{used_pct:.1f}% of {total:.1f} GB in use at scan time', 'Monitor memory usage during slowdowns.')
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            add('unknown', 'Memory figures could not be interpreted', str(memory), 'Inspect memory data in the original scan.')
    for disk in records(checks.get('disks', {}).get('data')):
        try:
            size, free = float(disk['SizeGB']), float(disk['FreeGB'])
            if size <= 0: continue
            free_pct = 100 * free / size
            drive = disk.get('DeviceID', 'Drive')
            if free_pct < 10:
                add('warning', f'Low disk space on {drive}', f'{free:.1f} GB free ({free_pct:.1f}%)', 'Review large files and Windows storage settings; do not delete files automatically.')
            elif free_pct < 20:
                add('info', f'Disk space getting low on {drive}', f'{free:.1f} GB free ({free_pct:.1f}%)', 'Review storage usage and plan cleanup if needed.')
        except (KeyError, TypeError, ValueError):
            add('unknown', 'Disk figures could not be interpreted', str(disk), 'Inspect disk data in the original scan.')
    for disk in records(checks.get('storage_health', {}).get('data')):
        status = str(disk.get('HealthStatus', '')).lower()
        if status and status != 'healthy':
            add('warning', f'Storage health status: {disk.get("FriendlyName", "Drive")}', f'Windows reported {disk.get("HealthStatus")}', 'Back up important files and check vendor-specific storage diagnostics.')
    for d in records(checks.get('drive_reliability',{}).get('data')):
        if not isinstance(d,dict) or d.get('Unavailable'):continue
        name=str(d.get('FriendlyName') or 'Physical drive')[:90]
        details=[]
        for k,unit in [('Temperature','°C'),('Wear','% wear reported'),('ReadErrorsUncorrected','uncorrected read errors'),('WriteErrorsUncorrected','uncorrected write errors')]:
            v=d.get(k)
            if isinstance(v,(int,float)) and v>=0:details.append(f'{k}: {v} {unit}')
        errors=sum(float(d.get(k) or 0) for k in ('ReadErrorsUncorrected','WriteErrorsUncorrected') if isinstance(d.get(k),(int,float)))
        temp=d.get('Temperature')
        if errors>0 or (isinstance(temp,(int,float)) and temp>=65):
            add('warning',f'Drive reliability requires review: {name}', '; '.join(details) or 'Drive reported reliability concerns', 'Back up important files; review drive health with the manufacturer’s diagnostic tool. Do not assume counters are universally supported.')
    event_summary = summarize_events(checks.get('event_log_analysis'))
    if event_summary['status']=='ok':
        groups=event_summary['groups']
        if groups:
            top=groups[:3]
            detail='; '.join(f"{g['description']} ({g['channel']} ID {g['event_id']}, {g['count_sampled']} sampled)" for g in top)
            add('info','Windows events worth reviewing',detail,
                'Compare timestamps with actual symptoms. Open Event Viewer or Reliability Monitor to investigate; IDs alone do not establish root cause.')
    elif event_summary['status']=='unavailable':
        add('unknown','Windows event analysis unavailable',event_summary.get('reason','Could not read event channels'),
            'Review Windows Event Viewer permissions or retry the scan.')
    if not findings:
        add('info', 'No rule-based alerts from available snapshot', 'No configured thresholds triggered', 'A single snapshot cannot rule out intermittent hardware or software problems.')
    return {'analyzer_version': '0.1.0', 'source_generated_at_utc': report.get('generated_at_utc'), 'analyzed_at_utc': datetime.now().astimezone().isoformat(), 'ai_generated': False, 'read_only': True, 'findings': findings, 'disclaimer': 'Rule-based analysis only. A successful collector does not establish device health. No repairs were performed.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default='scan.json')
    p.add_argument('--output', default='findings.json')
    a = p.parse_args()
    report = json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    result = analyze(report)
    Path(a.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PC Medic AI — Rule-based Findings (not yet AI)')
    for f in result['findings']:
        print(f"\n[{f['severity'].upper()}] {f['title']}\n  Evidence: {f['evidence']}\n  Next: {f['recommended_next_step']}")
    print(f'\nSaved findings to {Path(a.output).resolve()}')

if __name__ == '__main__':
    main()
