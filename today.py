"""The Today screen: a quick look when PC Medic opens, as a verdict and five status tiles.

Each tile has a state (good, note, attention, problem) and two voices: plain English for Home mode and
raw values for Technician mode. Results are cached briefly so reopening the screen is instant.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import system_checks
from performance_diagnostics import collect_performance

CACHE_SECONDS = 300
_cache = {'at': 0.0, 'data': None}
_lock = threading.Lock()
RANK = {'good': 0, 'note': 1, 'attention': 2, 'problem': 3}


def _tile(name, state, plain, tech, ask=None, open=None):
    """ask: a question for Ask PC Medic when the tile is clicked; open: a PC Medic screen to open instead."""
    return {'name': name, 'state': state, 'plain': plain, 'tech': tech, 'ask': ask, 'open': open}


def speed_tile(perf):
    if not perf:
        return _tile('Speed', 'note', 'PC Medic couldn’t measure speed just now.', 'Performance counters unavailable')
    cpu, mem, disk = perf.get('cpu'), perf.get('memory'), perf.get('disk')
    tech = f'CPU {cpu:.0f}% · RAM {mem:.0f}% of {perf.get("total_gb", "?")} GB · disk {disk:.0f}% busy ({perf["samples"]} s sample)'
    if mem >= 90 or cpu >= 85:
        busy = 'Memory is almost full' if mem >= 90 else 'The processor is very busy'
        return _tile('Speed', 'attention', f'{busy} right now ({max(mem, cpu):.0f}%), which can make things slow.', tech, 'My computer is slow')
    if mem >= 80 or cpu >= 60 or disk >= 60:
        return _tile('Speed', 'note', 'It’s working fairly hard right now, but nothing looks wrong.', tech, 'My computer is slow')
    return _tile('Speed', 'good', 'Running normally. Nothing is slowing it down right now.', tech, 'My computer is slow')


def storage_tile(d):
    if not d.get('available'):
        return _tile('Storage', 'note', 'PC Medic couldn’t read the drives.', system_checks.describe_technical('disk_health', d))
    tech = system_checks.describe_technical('disk_health', d)
    disks = system_checks.as_list(d.get('Disks'))
    unhealthy = [x for x in disks if str(x.get('Health', '')).lower() not in ('healthy', '')]
    errors = sum((x.get('ReadErrorsUncorrected') or 0) + (x.get('WriteErrorsUncorrected') or 0) for x in disks)
    c = next((v for v in system_checks.as_list(d.get('Volumes')) if v.get('Drive') == 'C:'), None)
    free, size = (c or {}).get('FreeGB'), (c or {}).get('SizeGB')
    space = f'{free:.0f} GB free of {size:.0f} GB.' if free is not None and size else ''
    if unhealthy or errors:
        return _tile('Storage', 'problem', 'The drive is reporting problems. Back up your files now.', tech, 'Is my SSD failing?')
    if free is not None and size and (free < 10 or free / size < 0.1):
        return _tile('Storage', 'attention', f'Almost full: {space} Windows needs room to run well.', tech, open='explorer')
    if free is not None and size and free < 30 and free / size < 0.2:
        return _tile('Storage', 'note', f'Getting full: {space}', tech, open='explorer')
    return _tile('Storage', 'good', f'{space} The drive reports healthy.'.strip(), tech, 'Is my SSD failing?')


def battery_tile(d):
    if not d.get('available') or not d.get('Present'):
        return _tile('Power', 'good', 'Plugged in: this computer has no battery to wear out.', system_checks.describe_technical('battery', d) if d.get('available') else 'Battery: unavailable')
    tech = system_checks.describe_technical('battery', d)
    health = d.get('HealthPercent')
    cycles = f' after {d["CycleCount"]} charge cycles' if d.get('CycleCount') else ''
    if health is None:
        return _tile('Battery', 'note', f'Battery at {d.get("ChargePercent")}%. Windows didn’t report its wear.', tech, 'How is my battery?')
    if health < 60:
        return _tile('Battery', 'attention', f'Worn: holds {health}% of its original charge{cycles}. A new battery would last much longer.', tech, 'I need a replacement battery')
    if health < 80:
        return _tile('Battery', 'note', f'Some wear: holds {health}% of its original charge{cycles}.', tech, 'How is my battery?')
    return _tile('Battery', 'good', f'Holds {health}% of its original charge{cycles}.', tech, 'How is my battery?')


def updates_tile(updates, reboot):
    tech = system_checks.describe_technical('updates', updates) if updates.get('available') else 'Windows Update history unavailable'
    if reboot.get('available') and (reboot.get('ComponentServicing') or reboot.get('WindowsUpdate')):
        return _tile('Updates', 'attention', 'A restart will finish installing updates.', tech + ' · reboot pending', 'Do I need to restart?')
    if not updates.get('available'):
        return _tile('Updates', 'note', 'PC Medic couldn’t read the update history.', tech)
    failures = system_checks.as_list(updates.get('Failures'))
    real = [f for f in failures if f.get('Error') != '0x80073D02']  # 0x80073D02: a Store app was open; it retries by itself
    if real:
        return _tile('Updates', 'note', f'{len(real)} update{"s" if len(real) != 1 else ""} didn’t install this month. Windows usually retries.', tech, 'Windows update keeps failing')
    if failures:
        return _tile('Updates', 'note', 'A few app updates didn’t finish. Windows will retry them.', tech, 'Windows update keeps failing')
    return _tile('Updates', 'good', 'Up to date. No failed updates this month.', tech)


def stability_tile(d):
    if not d.get('available'):
        return _tile('Stability', 'note', 'PC Medic couldn’t read the crash history.', 'Crash history unavailable')
    tech = system_checks.describe_technical('crashes', d)
    bsod = len(system_checks.as_list(d.get('BlueScreens')))
    restarts = len(system_checks.as_list(d.get('UnexpectedRestarts')))
    if bsod:
        return _tile('Stability', 'attention', f'It crashed with a blue screen {bsod} time{"s" if bsod != 1 else ""} this month.', tech, 'I got a blue screen')
    if restarts:
        return _tile('Stability', 'note', f'It shut off unexpectedly {"once" if restarts == 1 else f"{restarts} times"} this month. No crash screen.', tech, 'My PC restarts by itself')
    return _tile('Stability', 'good', 'No crashes or unexpected shutdowns this month.', tech)


def quick_performance(demo=False, seconds=3):
    samples = []
    for _ in range(seconds):
        try:
            samples.append(collect_performance(demo=demo))
        except Exception:
            pass
    if not samples:
        return None
    avg = lambda k: sum(s[k] or 0 for s in samples) / len(samples)
    total = samples[0].get('memory_total_mb')
    return {'cpu': avg('cpu_percent'), 'memory': avg('memory_used_percent'), 'disk': avg('disk_busy_percent'),
            'total_gb': round(total / 1024, 1) if total else None, 'samples': len(samples)}


def verdict(tiles):
    worst = max(tiles, key=lambda t: RANK[t['state']])['state']
    notes = sum(1 for t in tiles if t['state'] == 'note')
    needs = sum(1 for t in tiles if RANK[t['state']] >= 2)
    if worst == 'problem':
        return 'Something needs attention now', 'One part of this PC is reporting a problem. See the red tile below.'
    if needs:
        return f'{needs} thing{"s" if needs != 1 else ""} could use attention', 'Nothing urgent, but these are worth a few minutes.'
    if notes:
        return 'Your PC looks healthy', f'Nothing needs fixing right now. {("One small thing is" if notes == 1 else f"{notes} small things are")} worth knowing about.'
    return 'Your PC looks healthy', 'Everything PC Medic checked looks good.'


def build(demo=False):
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {name: pool.submit(system_checks.check, name) for name in ('battery', 'disk_health', 'crashes', 'updates', 'pending_reboot')}
        perf = quick_performance(demo)
        r = {name: job.result() for name, job in jobs.items()}
    tiles = [speed_tile(perf), storage_tile(r['disk_health']), battery_tile(r['battery']),
             updates_tile(r['updates'], r['pending_reboot']), stability_tile(r['crashes'])]
    title, subtitle = verdict(tiles)
    return {'title': title, 'subtitle': subtitle, 'tiles': tiles, 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}


def get(demo=False, refresh=False):
    with _lock:
        if not refresh and _cache['data'] and time.monotonic() - _cache['at'] < CACHE_SECONDS:
            return _cache['data']
    data = build(demo)
    with _lock:
        _cache.update(at=time.monotonic(), data=data)
    return data
