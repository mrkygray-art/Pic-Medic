"""The "What changed?" timeline: one small snapshot a day from the Today checks, compared over time.

Each time the Today screen runs its checks, today's snapshot is saved (replacing an earlier one from the same day):
free space per drive, battery health and runtime, crash and unexpected-shutdown times, the last successful Windows
update, a pending restart and the startup app names. Snapshots stay in timeline.json on this PC for KEEP_DAYS and
never go to AI (startup app names are personal). summary() says what changed over the last week; days() gives the
day-by-day timeline for Technician mode.
"""
import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import system_checks

DATA_FILE = None  # set by dashboard.py: <data folder>/timeline.json
KEEP_DAYS = 90
SUMMARY_DAYS = 7
LOCK = threading.Lock()
as_list = system_checks.as_list


# ---------- snapshots ----------
def snapshot(r, when=None):
    """Today's snapshot from the Today screen's check results (dict of check name -> data)."""
    when = when or datetime.now()
    disk, battery, crashes, updates, reboot, startup = (r.get(k) or {} for k in ('disk_health', 'battery', 'crashes', 'updates', 'pending_reboot', 'startup_apps'))
    snap = {'date': when.date().isoformat(), 'at': when.isoformat(timespec='seconds')}
    if disk.get('available'):
        snap['volumes'] = {v['Drive']: {'free_gb': v.get('FreeGB'), 'size_gb': v.get('SizeGB')} for v in as_list(disk.get('Volumes'))
                           if isinstance(v, dict) and v.get('Drive') and isinstance(v.get('FreeGB'), (int, float))}
    if battery.get('available') and battery.get('Present'):
        snap['battery'] = {'health': battery.get('HealthPercent'), 'runtime_min': battery.get('RuntimeFullMinutes')}
    if crashes.get('available'):
        snap['crashes'] = sorted({b.get('Date') for b in as_list(crashes.get('BlueScreens')) if isinstance(b, dict) and b.get('Date')} |
                                 {t for t in as_list(crashes.get('UnexpectedRestarts')) if isinstance(t, str)})
        snap['blue_screens'] = sorted(b.get('Date') for b in as_list(crashes.get('BlueScreens')) if isinstance(b, dict) and b.get('Date'))
    if updates.get('available'):
        snap['last_update'] = updates.get('LastSuccess')
    if reboot.get('available'):
        snap['restart_pending'] = bool(reboot.get('ComponentServicing') or reboot.get('WindowsUpdate'))
    if startup.get('available'):
        snap['startup'] = sorted({a.get('Name') for a in as_list(startup.get('Apps')) if isinstance(a, dict) and a.get('Name')})
    return snap


def read():
    try:
        data = json.loads(Path(DATA_FILE).read_text(encoding='utf-8')) if DATA_FILE and Path(DATA_FILE).exists() else []
    except (OSError, ValueError):
        return []
    return [s for s in data if isinstance(s, dict) and isinstance(s.get('date'), str)] if isinstance(data, list) else []


def record(snap):
    """Save today's snapshot, replacing one from the same day, and drop snapshots older than KEEP_DAYS."""
    if not DATA_FILE:
        return
    with LOCK:
        cutoff = (date.fromisoformat(snap['date']) - timedelta(days=KEEP_DAYS)).isoformat()
        entries = [s for s in read() if s['date'] != snap['date'] and s['date'] >= cutoff] + [snap]
        entries.sort(key=lambda s: s['date'])
        temp = Path(DATA_FILE).with_suffix('.tmp')
        temp.write_text(json.dumps(entries, indent=1), encoding='utf-8')
        temp.replace(DATA_FILE)


# ---------- comparing two snapshots ----------
def day_text(iso):
    """'2026-10-04...' -> 'Oct 4'."""
    try:
        d = datetime.fromisoformat(str(iso)[:19])
    except ValueError:
        return str(iso)
    return f'{d:%b} {d.day}'


def _item(kind, state, plain, tech):
    return {'kind': kind, 'state': state, 'plain': plain, 'tech': tech}


def compare(old, new, history=()):
    """What changed between two snapshots, as items with plain (Home) and tech (Technician) text."""
    since = day_text(old['date'])
    items = []
    for drive, now in (new.get('volumes') or {}).items():
        before = (old.get('volumes') or {}).get(drive)
        if not before or not isinstance(before.get('free_gb'), (int, float)):
            continue
        size = now.get('size_gb') or before.get('size_gb') or 0
        delta = now['free_gb'] - before['free_gb']
        if abs(delta) < max(2, 0.02 * size):
            continue
        low = size and now['free_gb'] / size < 0.1
        if delta < 0:
            items.append(_item('storage', 'attention' if low else 'note',
                               f'Drive {drive} has {-delta:.0f} GB less free space than on {since} ({now["free_gb"]:.0f} GB free now).'
                               + (' It is almost full.' if low else ''),
                               f'{drive} free {before["free_gb"]:.1f} → {now["free_gb"]:.1f} GB ({delta:+.1f}) of {size:.0f} GB'))
        else:
            items.append(_item('storage', 'good', f'Drive {drive} has {delta:.0f} GB more free space than on {since} ({now["free_gb"]:.0f} GB free now).',
                               f'{drive} free {before["free_gb"]:.1f} → {now["free_gb"]:.1f} GB ({delta:+.1f}) of {size:.0f} GB'))
    b0, b1 = (old.get('battery') or {}).get('health'), (new.get('battery') or {}).get('health')
    if isinstance(b0, int) and isinstance(b1, int) and abs(b1 - b0) >= 1:
        items.append(_item('battery', 'note' if b1 < b0 else 'good',
                           f'Battery health went from {b0}% to {b1}% of new since {since}.' + (' A replacement battery may have been fitted.' if b1 - b0 >= 10 else ''),
                           f'Battery health {b0}% → {b1}%'))
    new_crashes = [t for t in new.get('crashes') or [] if t > old.get('at', old['date']) and t not in (old.get('crashes') or [])]
    if new_crashes:
        bsod = [t for t in new_crashes if t in (new.get('blue_screens') or [])]
        earlier = sorted({t for s in history for t in s.get('crashes') or []} | set(old.get('crashes') or []))
        earlier = [t for t in earlier if t < new_crashes[0]]
        what = 'blue-screen crash' if len(bsod) == len(new_crashes) else 'crash or unexpected shutdown'
        plain = (f'It had a {what} on {day_text(new_crashes[0])}' if len(new_crashes) == 1 else
                 f'It had {len(new_crashes)} crashes or unexpected shutdowns since {since}')
        if earlier:
            gap = (datetime.fromisoformat(new_crashes[0][:19]) - datetime.fromisoformat(earlier[-1][:19])).days
            if gap >= 7:
                plain += f', the first in {gap} days'
        upd = new.get('last_update')
        if upd and upd > old.get('at', '') and upd <= new_crashes[0] and (datetime.fromisoformat(new_crashes[0][:19]) - datetime.fromisoformat(upd[:19])).days <= 3:
            plain += f'. It came after Windows installed updates on {day_text(upd)}'
        items.append(_item('crashes', 'attention', plain + '.', f'{len(new_crashes)} new crash event(s): ' + ', '.join(t.replace('T', ' ')[:16] for t in new_crashes)
                           + (f' ({len(bsod)} bugcheck)' if bsod else '')))
    if new.get('last_update') and old.get('last_update') and new['last_update'] > old['last_update']:
        items.append(_item('updates', 'good', f'Windows installed updates since {since} (the latest on {day_text(new["last_update"])}).',
                           f'Last successful update {old["last_update"].replace("T", " ")[:16]} → {new["last_update"].replace("T", " ")[:16]}'))
    if 'startup' in old and 'startup' in new:
        added = sorted(set(new['startup']) - set(old['startup']))
        removed = sorted(set(old['startup']) - set(new['startup']))
        if added:
            items.append(_item('startup', 'note', f'{len(added)} new app{"s" if len(added) != 1 else ""} start{"s" if len(added) == 1 else ""} with Windows since {since}: '
                               + ', '.join(added[:5]) + (f' and {len(added) - 5} more' if len(added) > 5 else '') + '.',
                               'Startup added: ' + ', '.join(added)))
        if removed:
            items.append(_item('startup', 'good', f'{len(removed)} app{"s" if len(removed) != 1 else ""} no longer start{"s" if len(removed) == 1 else ""} with Windows: '
                               + ', '.join(removed[:5]) + (f' and {len(removed) - 5} more' if len(removed) > 5 else '') + '.',
                               'Startup removed: ' + ', '.join(removed)))
    if new.get('restart_pending'):
        if old.get('restart_pending'):
            items.append(_item('restart', 'attention', f'A restart to finish updates has been waiting since at least {since}.', 'Reboot pending (also on ' + old['date'] + ')'))
        else:
            items.append(_item('restart', 'note', 'A restart is now needed to finish installing updates.', 'Reboot pending (new)'))
    order = {'crashes': 0, 'storage': 1, 'restart': 2, 'battery': 3, 'startup': 4, 'updates': 5}
    return sorted(items, key=lambda i: order.get(i['kind'], 9))


# ---------- what the page shows ----------
def summary(entries=None, today=None):
    """What changed over about the last week: compares today's snapshot with the oldest one from the last SUMMARY_DAYS
    days (or, if there is none, the most recent earlier one)."""
    entries = read() if entries is None else entries
    if not entries:
        return {'tracking_since': None, 'since': None, 'items': []}
    latest = entries[-1]
    earlier = [s for s in entries[:-1] if s['date'] < latest['date']]
    first = entries[0]['date']
    if not earlier:
        return {'tracking_since': first, 'since': None, 'items': []}
    window = (date.fromisoformat(latest['date']) - timedelta(days=SUMMARY_DAYS)).isoformat()
    base = next((s for s in earlier if s['date'] >= window), earlier[-1])
    history = [s for s in earlier if s['date'] < base['date']]
    return {'tracking_since': first, 'since': base['date'], 'items': compare(base, latest, history)}


def days(entries=None, limit=30):
    """Day-by-day changes, newest first, for the Technician timeline."""
    entries = read() if entries is None else entries
    out = []
    for i in range(len(entries) - 1, 0, -1):
        items = compare(entries[i - 1], entries[i], entries[:i - 1])
        if items:
            out.append({'date': entries[i]['date'], 'since': entries[i - 1]['date'], 'items': items})
        if len(out) >= limit:
            break
    return {'tracking_since': entries[0]['date'] if entries else None, 'snapshots': len(entries), 'days': out}
