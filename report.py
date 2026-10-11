"""Technician report: one self-contained HTML page to print, save as PDF, or attach to a ticket.

Built locally from read-only data. It includes app and model names a technician needs, but no serial
numbers, user names, file paths, IP or MAC addresses.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import escape

import system_checks
from analyze import analyze
from event_log_analyzer import summarize_events

VERSION = '1.16.15'
REPORT_CHECKS = ('battery', 'disk_health', 'crashes', 'updates', 'pending_reboot', 'startup_apps', 'listening_ports')

STYLE = """
:root{--ink:#162239;--muted:#5b6b82;--line:#dce4ef;--soft:#f4f7fb;--accent:#2f6fd8;--bad:#b3261e;--warn:#9a6700;--good:#1a7f37}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:14px/1.55 "Segoe UI",Inter,system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 24px 48px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:22px}
h1{font-size:24px;margin:0}h2{font-size:16px;margin:26px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.meta{color:var(--muted);font-size:13px;text-align:right}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{width:32%;color:var(--muted);font-weight:600}
.check{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0;white-space:pre-wrap}
.finding{border-left:4px solid var(--line);padding:6px 12px;margin:8px 0}.finding.high,.finding.critical,.finding.urgent{border-color:var(--bad)}.finding.medium,.finding.warning{border-color:var(--warn)}.finding.low,.finding.info{border-color:var(--good)}
.finding small{display:block;color:var(--muted)}
.qa{margin:10px 0}.q{font-weight:600}.a{white-space:pre-wrap;color:#24344d;margin-left:14px}
#notes{min-height:110px;border:1px dashed #9fb1c9;border-radius:10px;padding:10px 12px;white-space:pre-wrap}#notes:empty:before{content:"Click to type notes before printing (work performed, parts ordered, follow-up).";color:var(--muted)}
.muted{color:var(--muted)}.actions{margin:0 0 18px}button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
footer{margin-top:30px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:10px}
@media print{.actions{display:none}main{padding:0}#notes{border-style:solid}h2{break-after:avoid}.check,.finding,.qa{break-inside:avoid}}
@media (max-width:600px){header{flex-direction:column}.meta{text-align:left}th{width:42%}}
"""

def _rows(pairs):
    return ''.join(f'<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>' for k, v in pairs if v not in (None, '', []))

def computer_section(overview):
    if not overview.get('available'):return '<p class="muted">Computer details unavailable: ' + escape(str(overview.get('reason') or '')) + '</p>'
    win = overview.get('windows') or {}
    cpu = overview.get('processor') or {}
    ram = '; '.join(f'{m.get("size_gb")} GB {m.get("speed_mts") or "?"} MT/s ({m.get("part_number") or "part unknown"})' for m in overview.get('ram_modules') or [])
    drives = '; '.join(f'{d.get("model")} ({d.get("size_gb")} GB)' for d in overview.get('drives') or [])
    kind = {'laptop': 'Laptop', 'desktop': 'Desktop', 'all-in-one': 'All-in-one desktop', 'virtual': 'Virtual machine'}.get(overview.get('device_type'))
    if kind and overview.get('identified_by') == 'motherboard':kind += ' (custom-built, identified by its motherboard)'
    return '<table>' + _rows([
        ('Type', kind), ('Manufacturer', overview.get('manufacturer')), ('Model', ' '.join(x for x in (overview.get('product_name'), overview.get('model')) if x)),
        ('Windows', ' '.join(str(x) for x in (win.get('Caption'), f'(build {win.get("BuildNumber")})' if win.get('BuildNumber') else '') if x)),
        ('Processor', f'{cpu.get("Name")} · {cpu.get("NumberOfCores")} cores / {cpu.get("NumberOfLogicalProcessors")} threads' if cpu.get('Name') else None),
        ('Memory', f'{overview.get("ram_total_gb")} GB total' + (f' · {ram}' if ram else '')),
        ('Memory slots reported', overview.get('memory_slots_reported')),
        ('Graphics', ', '.join(overview.get('graphics') or [])), ('Storage', drives),
        ('Battery part number', ', '.join(overview.get('battery_part_numbers') or [])), ('BIOS', overview.get('bios_version')),
    ]) + '</table>'

def findings_section(scan):
    if not scan:return '<p class="muted">No Health Check has been run on this computer yet.</p>'
    when = scan.get('generated_at_utc')
    findings = analyze(scan).get('findings') or []
    head = f'<p class="muted">From the Health Check on {escape(str(when)[:16].replace("T", " "))} UTC. {len(findings)} finding(s).</p>'
    if not findings:return head + '<p>No problems were found in that Health Check.</p>'
    return head + ''.join(f'<div class="finding {escape(str(f.get("severity", "")).lower())}"><strong>{escape(str(f.get("title", "")))}</strong>'
                          f'<small>{escape(str(f.get("severity", "")).title())} · Next step: {escape(str(f.get("recommended_next_step") or "—"))}</small></div>' for f in findings[:15])

def events_section(scan):
    events = summarize_events((scan or {}).get('checks', {}).get('event_log_analysis')) if scan else {'status': 'unavailable'}
    groups = events.get('groups') or []
    if events.get('status') != 'ok':return '<p class="muted">Event logs were not included in the latest Health Check.</p>'
    if not groups:return '<p>No serious Windows errors in the 24 hours before the Health Check.</p>'
    return '<table>' + ''.join(f'<tr><th>{escape(g["description"])}</th><td>{g["count_sampled"]}× · event {g["event_id"]} · {escape(g["channel"])} · latest {escape(str(g.get("latest", ""))[:16])}</td></tr>' for g in groups) + '</table>'

def conversation_section(turns):
    clean = [(str(t.get('q') or '')[:500], str(t.get('a') or '')[:4000]) for t in (turns or [])[:40] if isinstance(t, dict) and (t.get('q') or t.get('a'))]
    if not clean:return '<p class="muted">No questions were asked in this session.</p>'
    return ''.join(f'<div class="qa">{f"<div class=q>Q: {escape(q)}</div>" if q else ""}<div class="a">{escape(a)}</div></div>' for q, a in clean)

def build(overview, scan, checks, turns, generated=None):
    generated = generated or datetime.now()
    model = ' '.join(x for x in (overview.get('manufacturer'), overview.get('product_name'), overview.get('model')) if x) or 'This computer'
    check_html = ''.join(f'<div class="check">{escape(system_checks.describe(name, checks[name]))}</div>' for name in REPORT_CHECKS if name in checks)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PC Medic report · {escape(model)}</title><style>{STYLE}</style></head><body><main>
<header><div><h1>PC Medic technician report</h1><div>{escape(model)}</div></div>
<div class="meta">Generated {escape(generated.strftime('%Y-%m-%d %H:%M'))}<br>PC Medic AI {VERSION}</div></header>
<div class="actions"><button type="button" onclick="window.print()">Print / Save as PDF</button></div>
<h2>Computer</h2>{computer_section(overview)}
<h2>Health Check findings</h2>{findings_section(scan)}
<h2>Current checks</h2>{check_html or '<p class="muted">Checks unavailable.</p>'}
<h2>Recent Windows errors</h2>{events_section(scan)}
<h2>Questions and answers this session</h2>{conversation_section(turns)}
<h2>Technician notes</h2><div id="notes" contenteditable="true"></div>
<footer>Read-only diagnostics: PC Medic did not change any settings, files or drivers. Event IDs and findings are leads, not proof of cause.
Serial numbers, user names, IP and MAC addresses are not included.</footer>
</main></body></html>"""

def generate(scan, turns):
    """Run the current checks in parallel, then build the page."""
    from assistant import computer_overview
    with ThreadPoolExecutor(max_workers=4) as pool:
        overview_job = pool.submit(computer_overview)
        jobs = {name: pool.submit(system_checks.check, name) for name in REPORT_CHECKS}
        checks = {name: job.result() for name, job in jobs.items()}
        overview = overview_job.result()
    return build(overview, scan, checks, turns)
