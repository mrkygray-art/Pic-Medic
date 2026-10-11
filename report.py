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

from version import VERSION
REPORT_CHECKS = ('security', 'event_signals', 'battery', 'disk_health', 'crashes', 'updates', 'pending_reboot', 'startup_apps', 'listening_ports')

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
h3{font-size:14px;margin:16px 0 6px}
.service th{width:16%}.service td{width:34%}.field{display:inline-block;min-width:170px;min-height:1.4em;border-bottom:1px dotted #9fb1c9;outline:none}.field:empty:before{content:attr(data-placeholder);color:var(--muted)}
.glance th{width:17%}.glance td.st{width:132px}.chip{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12px;font-weight:600;white-space:nowrap}
.chip.good{background:#e6f4ea;color:var(--good)}.chip.note{background:#eaf3fc;color:#005fb8}.chip.warn{background:#fff4ce;color:var(--warn)}.chip.bad{background:#fde7e9;color:var(--bad)}
.steps{margin:4px 0 0;padding-left:22px}.steps li{margin:4px 0}
.sign{display:flex;gap:48px;margin-top:26px}.sign span{flex:1;border-top:1px solid var(--ink);padding-top:4px;font-size:12px;color:var(--muted)}
.appendix{margin-top:36px}.appendix .check{font-size:12.5px}.tech{font-family:Consolas,"Cascadia Mono",monospace;font-size:11.5px;color:var(--muted);margin-top:6px;white-space:pre-wrap}
.actions label{margin-left:12px}.actions .muted{margin-left:12px;font-size:12px}
body.no-appendix .appendix{display:none}
@media print{@page{margin:14mm}body{font-size:12px}main{padding:0}.actions{display:none}#notes{border-style:solid;min-height:80px}h2{break-after:avoid;margin-top:16px}
 .check,.finding,.qa,tr{break-inside:avoid}.appendix{break-before:page;margin-top:0}.field{border-bottom:1px solid #999}.field:empty:before,#notes:empty:before{content:""}}
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

def cases_section(cases):
    if not cases:return '<p class="muted">No guided troubleshooting on this computer yet.</p>'
    status = {'resolved': 'Fixed', 'improved': 'Improved', 'not_resolved': 'Not fixed', 'recommended': 'In progress', 'validating': 'In progress', 'asking': 'Started'}
    return '<table>' + ''.join(f'<tr><th>{escape(str(c.get("updated", ""))[:10])} · {escape(status.get(c.get("status"), str(c.get("status"))))}</th>'
                               f'<td>{escape(c.get("problem") or "")}{(" (" + escape(c["context"]) + ")") if c.get("context") else ""}'
                               f'{("<br><span class=muted>" + escape(c["outcome"]) + "</span>") if c.get("outcome") else ""}</td></tr>' for c in cases[:15]) + '</table>'

STATE = {'good': ('Good', 'good'), 'note': ('Worth knowing', 'note'), 'attention': ('Needs attention', 'warn'), 'problem': ('Problem', 'bad'), None: ('Not checked', 'note')}
RANK = {'good': 0, 'note': 1, 'attention': 2, 'problem': 3}


def _worst(states):
    states = [s for s in states if s in RANK]
    return max(states, key=RANK.get) if states else None


def glance(checks):
    """The at-a-glance rows: (area, state, finding). Measured facts only; no forecasts."""
    rows, lst = [], system_checks.as_list
    sec = checks.get('security') or {}
    if sec.get('available'):
        items = system_checks.security_items(sec)
        bad = [i['area'] for i in items if i['state'] in ('attention', 'problem')]
        notes = [i['area'] for i in items if i['state'] == 'note']
        rows.append(('Security', _worst(i['state'] for i in items),
                     (f'Needs attention: {", ".join(bad)}. ' if bad else 'Antivirus, firewall, UAC, Secure Boot and updates are in order. ') + (f'Worth knowing: {", ".join(notes)}.' if notes else '')))
    disk = checks.get('disk_health') or {}
    if disk.get('available'):
        disks = [x for x in lst(disk.get('Disks')) if isinstance(x, dict)]
        errors = sum((x.get('ReadErrorsUncorrected') or 0) + (x.get('WriteErrorsUncorrected') or 0) for x in disks)
        unhealthy = [x for x in disks if str(x.get('Health', '')).lower() not in ('healthy', '')]
        c = next((v for v in lst(disk.get('Volumes')) if isinstance(v, dict) and v.get('Drive') == 'C:' and v.get('SizeGB')), None)
        low = c and (c.get('FreeGB') or 0) / c['SizeGB'] < 0.1
        rows.append(('Storage', 'problem' if errors or unhealthy else 'attention' if low else 'good',
                     '; '.join(f'{x.get("Name")} ({x.get("MediaType")}): {x.get("Health")}' for x in disks) + (f'. C: {c.get("FreeGB")} GB free of {c["SizeGB"]} GB.' if c else '.')))
    bat = checks.get('battery') or {}
    if bat.get('available'):
        h = bat.get('HealthPercent')
        rows.append(('Battery', None if not bat.get('Present') else 'good' if (h or 0) >= 80 else 'note' if (h or 0) >= 60 else 'attention',
                     'No battery (desktop or AC-only).' if not bat.get('Present') else
                     f'Measured capacity {h}% of original' + (f' ({bat["FullChargeCapacity_mWh"]:,} of {bat["DesignCapacity_mWh"]:,} mWh)' if isinstance(bat.get('FullChargeCapacity_mWh'), int) and isinstance(bat.get('DesignCapacity_mWh'), int) else '') + (f', {bat["CycleCount"]} charge cycles.' if bat.get('CycleCount') else '.')
                     if h is not None else 'Windows did not report the battery capacity.'))
    cr = checks.get('crashes') or {}
    if cr.get('available'):
        bsod, hard = lst(cr.get('BlueScreens')), lst(cr.get('UnexpectedRestarts'))
        rows.append(('Stability', 'attention' if bsod else 'note' if hard else 'good',
                     f'Last 30 days: {len(bsod)} blue screen{"s" if len(bsod) != 1 else ""}, {len(hard)} unexpected restart{"s" if len(hard) != 1 else ""} or power loss{"es" if len(hard) != 1 else ""}.'))
    up, rb = checks.get('updates') or {}, checks.get('pending_reboot') or {}
    if up.get('available'):
        real = [f for f in lst(up.get('Failures')) if isinstance(f, dict) and f.get('Error') != '0x80073D02']
        pending = rb.get('ComponentServicing') or rb.get('WindowsUpdate')
        rows.append(('Windows Update', 'attention' if pending else 'note' if real else 'good',
                     f'{up.get("SuccessCount", 0)} installed, {len(real)} failed (not counting Store apps in use) in 30 days.' + (' A restart is pending to finish updates.' if pending else '')))
    sig = checks.get('event_signals') or {}
    if sig.get('available'):
        items = [i for i in system_checks.signal_items(sig) if i['state'] != 'good']
        rows.append(('Windows logs', _worst(i['state'] for i in items) or 'good',
                     ('Warning signs: ' + '; '.join(f'{i["area"]} ×{(sig.get(k) or {}).get("Count")}' for i in items for k, v in system_checks.SIGNALS_TEXT.items() if v[0] == i['area']) + '.') if items else 'No warning signs in the last 30 days.'))
    ports = checks.get('listening_ports') or {}
    if ports.get('available'):
        bound = [t for t in system_checks.port_list(ports) if t['Scope'] != 'loopback']
        fw = [f for f in lst(ports.get('Firewall')) if isinstance(f, dict)]
        off = [f['Profile'] for f in fw if not f.get('Enabled')]
        rows.append(('Network', 'attention' if off else 'note' if bound else 'good',
                     f'{len(bound)} TCP ports listen on a network interface. ' + (f'Firewall OFF for {", ".join(off)}. ' if off else 'Firewall on for all network types. ' if fw else '') +
                     (f'Network type: {", ".join(lst(ports.get("NetworkTypes")))}. ' if ports.get('NetworkTypes') else '') + 'Listening is not the same as exposed; see the appendix.'))
    return rows


def next_steps(checks, scan):
    """Concrete actions, most important first, from the checks and the Health Check."""
    out = []
    sec = checks.get('security') or {}
    if sec.get('available'):
        out += [i['plain'] for i in sorted(system_checks.security_items(sec), key=lambda i: -RANK[i['state']]) if i['state'] in ('problem', 'attention')]
    import coordinator  # the same correlation rules as an investigation, each with what to do
    out += [f'{f["title"]}: {f["plain"]}' for f in coordinator.correlate('general', checks) if f['weight'] >= 3 and f['title'] != 'Windows Update']
    up = checks.get('updates') or {}
    if up.get('available'):
        import error_codes
        for code, group in system_checks.update_errors(up)[:2]:
            info = error_codes.lookup(code) if code and code != '0x80073D02' else None
            if info:
                out.append(f'Windows Update error {code} ({len(group)}×): {info["fix"]}')
    rb = checks.get('pending_reboot') or {}
    if rb.get('ComponentServicing') or rb.get('WindowsUpdate'):
        out.append('Restart the computer to finish installing Windows updates.')
    for f in (analyze(scan).get('findings') or [])[:5] if scan else []:
        if f.get('recommended_next_step'):
            out.append(f'{f.get("title")}: {f["recommended_next_step"]}')
    seen, unique = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:8]


def service_section(service):
    s = service or {}
    field = lambda key, label, ph: (f'<th>{label}</th><td><span class="field" contenteditable="true" data-placeholder="{ph}">{escape(str(s.get(key) or "")[:120])}</span></td>')
    return ('<table class="service"><tr>' + field('customer', 'Customer', 'Customer name') + field('ticket', 'Ticket number', 'Ticket #') + '</tr><tr>' +
            field('technician', 'Technician', 'Technician name') + field('date', 'Service date', 'Date') + '</tr></table>')


def glance_section(rows):
    if not rows:
        return '<p class="muted">Checks unavailable.</p>'
    return '<table class="glance">' + ''.join(f'<tr><th>{escape(area)}</th><td class="st"><span class="chip {STATE[state][1]}">{STATE[state][0]}</span></td><td>{escape(text)}</td></tr>'
                                             for area, state, text in rows) + '</table>'


def build(overview, scan, checks, turns, generated=None, cases=None, service=None):
    generated = generated or datetime.now()
    service = dict(service or {})
    service.setdefault('date', generated.strftime('%Y-%m-%d'))
    model = ' '.join(x for x in (overview.get('manufacturer'), overview.get('product_name'), overview.get('model')) if x) or 'This computer'
    steps = next_steps(checks, scan)
    details = ''.join(f'<div class="check">{escape(system_checks.describe(name, checks[name]))}<div class="tech">{escape(system_checks.describe_technical(name, checks[name]))}</div></div>'
                      for name in REPORT_CHECKS if name in checks)
    deep = system_checks.deep_scan()
    deep_html = ''
    if deep:
        import deep_scan
        deep_html = f'<h3>Deep scan</h3><div class="check">{escape(deep_scan.describe(deep))}<div class="tech">{escape(deep_scan.describe(deep, True))}</div></div>'
    history = f'<h2>Troubleshooting history</h2>{cases_section(cases)}' if cases else ''
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PC Medic report · {escape(model)}</title><style>{STYLE}</style></head><body><main>
<header><div><h1>PC Medic technician report</h1><div>{escape(model)}</div></div>
<div class="meta">Generated {escape(generated.strftime('%Y-%m-%d %H:%M'))}<br>PC Medic AI {VERSION}</div></header>
<div class="actions"><button type="button" onclick="window.print()">Print / Save as PDF</button>
<label><input type="checkbox" checked onchange="document.body.classList.toggle('no-appendix',!this.checked)"> Include the technical appendix</label>
<span class="muted">Click any field or the notes to edit before printing.</span></div>
<h2>Service details</h2>{service_section(service)}
<h2>At a glance</h2>{glance_section(glance(checks))}
<h2>Recommended next steps</h2>{('<ol class="steps">' + ''.join(f'<li>{escape(s)}</li>' for s in steps) + '</ol>') if steps else '<p>No action needed from the checks PC Medic ran.</p>'}
<h2>Computer</h2>{computer_section(overview)}
<h2>Health Check findings</h2>{findings_section(scan)}
{history}
<h2>Technician notes</h2><div id="notes" contenteditable="true"></div>
<div class="sign"><span>Technician signature</span><span>Date</span></div>
<footer>Read-only diagnostics: PC Medic did not change any settings, files or drivers. Findings and event IDs are leads, not proof of cause; measured values are as reported by Windows at the time of this report.
Serial numbers, user names, IP and MAC addresses are not included. The customer name and ticket number are only in this report; PC Medic does not save or send them.</footer>
<section class="appendix"><h2>Appendix: technical details</h2>
<h3>Checks</h3>{details or '<p class="muted">Checks unavailable.</p>'}
{deep_html}
<h3>Recent Windows errors</h3>{events_section(scan)}
<h3>Questions and answers this session</h3>{conversation_section(turns)}
</section>
</main></body></html>"""


def generate(scan, turns, service=None):
    """Run the current checks in parallel, then build the page."""
    from assistant import computer_overview
    with ThreadPoolExecutor(max_workers=4) as pool:
        overview_job = pool.submit(computer_overview)
        jobs = {name: pool.submit(system_checks.check, name) for name in REPORT_CHECKS}
        checks = {name: job.result() for name, job in jobs.items()}
        overview = overview_job.result()
    import troubleshooter
    return build(overview, scan, checks, turns, cases=troubleshooter.history(), service=service)
