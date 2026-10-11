"""PC Medic AI: localhost-only, read-only diagnostics and guided troubleshooting."""
import argparse
import json
import os
import secrets
import subprocess
import sys
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from hardware_advisor import inventory as hardware_inventory
from parts_research import research as parts_research, preview as parts_preview
from network_advisor import inventory as network_inventory
from intent_engine import classify as classify_intent
from analyze import analyze
from ai_engine import ask as ai_ask, safe_summary, sanitize_investigation
from process_diagnostics import collect_processes
from performance_diagnostics import collect_performance, summarize
from storage_explorer import inventory, recycle
from device_diagnostics import inventory as device_inventory
import system_checks
from version import VERSION
import local_security
import socket
import assistant
import settings
import troubleshooter
import report as tech_report

BASE = Path(__file__).resolve().parent
FROZEN = getattr(sys, 'frozen', False)
# A packaged .exe unpacks to a temporary folder, so saved data lives in the user's AppData instead.
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PC Medic' if FROZEN else BASE
DATA.mkdir(parents=True, exist_ok=True)
SCAN = DATA / 'scan.json'
HISTORY = DATA / 'scan_history.json'
assistant.SCAN_PATH = str(SCAN)  # Claude's get_latest_health_check tool reads the same scan
settings.DATA_FILE = str(DATA / 'settings.json')  # trial count and update preference
troubleshooter.CASES_FILE = str(DATA / 'cases.json')  # saved troubleshooting cases
HISTORY_LOCK = threading.Lock()
LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(32)
# One diagnostic at a time across every browser window: the window that starts a Health Check or
# Performance Watch holds a lease, renewed by each sample; a closed tab's lease expires on its own.
ACTIVITY = {'kind': None, 'owner': None, 'until': 0.0}
ACTIVITY_LOCK = threading.Lock()
ACTIVITY_LABELS = {'health': 'A Health Check', 'watch': 'A Performance Watch', 'storage': 'A Storage Explorer search', 'troubleshoot': 'A troubleshooting check'}
LEASE_SECONDS = 90

def activity_conflict(owner, kind=None, seconds=LEASE_SECONDS):
 """Return the label of another window's running diagnostic, or None after claiming/renewing it for owner."""
 with ACTIVITY_LOCK:
  now=time.monotonic()
  if ACTIVITY['owner'] and now<ACTIVITY['until'] and ACTIVITY['owner']!=owner:
   return ACTIVITY_LABELS[ACTIVITY['kind']]
  if kind:ACTIVITY.update(kind=kind,owner=owner,until=now+seconds)
  elif ACTIVITY['owner']==owner:ACTIVITY['until']=max(ACTIVITY['until'],now+seconds)
  return None

def release_activity(owner):
 with ACTIVITY_LOCK:
  if ACTIVITY['owner']==owner:ACTIVITY.update(kind=None,owner=None,until=0.0)

def valid_owner(value):
 return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9-]{8,64}',value))
DEMO = {
 'generated_at_utc':'2026-10-09T17:00:00+00:00', 'platform':'Windows',
 'checks':{
 'os':{'status':'ok','data':{'Caption':'Microsoft Windows 11 Pro','Version':'10.0.26100'}},
 'cpu':{'status':'ok','data':{'Name':'Demo CPU · 8 cores','LoadPercentage':24}},
 'memory':{'status':'ok','data':{'TotalGB':16,'FreeGB':1.4}},
 'disks':{'status':'ok','data':[{'DeviceID':'C:','SizeGB':476,'FreeGB':73.2}]},
 'storage_health':{'status':'ok','data':{'FriendlyName':'Demo SSD','HealthStatus':'Healthy'}},
 'network':{'status':'ok','data':{'InterfaceDescription':'Demo Wi-Fi','Status':'Up'}},
 'event_log_analysis':{'status':'ok','data':{'window_hours':24,'limit_per_channel':80,'channels':[{'name':'System','status':'ok','events':[{'Id':20,'ProviderName':'Microsoft-Windows-WindowsUpdateClient','TimeCreated':'2026-10-09T12:00:00'}]}]}}
 }}

def get_report(demo):
 if demo: return DEMO
 if not SCAN.exists(): raise FileNotFoundError('No scan.json yet. Click Run New Scan.')
 report = json.loads(SCAN.read_text(encoding='utf-8-sig'))
 if not isinstance(report, dict) or not isinstance(report.get('checks'),dict):
  raise ValueError('Invalid scan: missing checks')
 return report

def watch_only_report(investigation):
 """Use a clearly labeled partial report when no full health scan exists."""
 if not isinstance(investigation,dict) or not isinstance(investigation.get('performance_samples'),list) or not investigation['performance_samples']:
  raise FileNotFoundError('No health scan or performance evidence is available. Run a diagnostic first.')
 return {'generated_at_utc':datetime.now(timezone.utc).isoformat(), 'checks':{},
         'evidence_scope':'performance_watch_only', 'partial':True}


# Approved built-in Windows tools only. Opening a tool never applies a repair.
WINDOWS_TOOLS = {
 # PowerShell 5.1 lives in its own folder; System32\powershell.exe does not exist.
 'powershell': ('Windows PowerShell', r'WindowsPowerShell\v1.0\powershell.exe'),
 'command-prompt': ('Command Prompt', 'cmd.exe'),
 'optimize': ('Optimize Drives', 'dfrgui.exe'),
 'event-viewer': ('Event Viewer', 'eventvwr.msc'),
 'services': ('Services', 'services.msc'),
 'startup': ('Startup Apps', 'ms-settings:startupapps'),
 'system-config': ('System Configuration', 'msconfig.exe'),
 'device-manager': ('Device Manager', 'devmgmt.msc'),
 'task-manager': ('Task Manager', 'taskmgr.exe'),
 'windows-update': ('Windows Update', 'ms-settings:windowsupdate'),
 'reliability': ('Reliability Monitor', 'perfmon.exe'),
 'storage-settings': ('Windows Storage Settings', 'ms-settings:storagesense'),
 'display': ('Display Settings', 'ms-settings:display'),
 'power': ('Power & Battery Settings', 'ms-settings:powersleep'),
 'lockscreen': ('Lock Screen Settings', 'ms-settings:lockscreen'),
 'windows-security': ('Windows Security', 'windowsdefender:'),
 'resource-monitor': ('Resource Monitor', 'resmon.exe'),
 'system-information': ('System Information', 'msinfo32.exe'),
 'task-scheduler': ('Task Scheduler', 'taskschd.msc'),
 'disk-management': ('Disk Management', 'diskmgmt.msc'),
 'computer-management': ('Computer Management', 'compmgmt.msc'),
 'network-connections': ('Network Connections', 'ncpa.cpl'),
 'memory-diagnostic': ('Windows Memory Diagnostic', 'mdsched.exe'),
 'advanced-startup': ('Advanced Startup / Recovery', 'ms-settings:recovery'),
 'security-offline-scan': ('Windows Security scan options', 'windowsdefender://threat'),
}

SHELL_EXECUTE_ERRORS = {
 0: 'Windows is out of memory or resources. Close some programs and try again.',
 2: 'Windows could not find this program on this PC.',
 3: 'Windows could not find the folder for this program.',
 5: 'Administrator approval was declined, or this account is not allowed to open it. Nothing was changed.',
 31: 'No program is set up to open this on this PC.',
}

def shell_open_windows(executable, arguments=None, *, elevate_if_required=False):
 """Launch an allowlisted Windows tool with ShellExecute, preserving Windows UAC."""
 import ctypes
 from ctypes import wintypes
 shell = ctypes.WinDLL('shell32', use_last_error=True)
 shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
 shell.ShellExecuteW.restype = ctypes.c_void_p
 # 'open' already shows the UAC prompt for tools that need admin rights. Retrying with 'runas' after the
 # user cancels (error 5) only asked a second time, so a cancel is reported, not retried.
 result = shell.ShellExecuteW(None, 'open', str(executable), arguments, None, 1) or 0  # c_void_p gives None for 0
 if result <= 32:
  raise RuntimeError(SHELL_EXECUTE_ERRORS.get(result, f'Windows could not open the utility (error {result}).'))


def launch_windows_tool(tool):
 if os.name != 'nt': raise RuntimeError('Windows only')
 windir = Path(os.environ.get('WINDIR', r'C:\Windows'))
 system32 = windir / 'System32'
 label, target = WINDOWS_TOOLS[tool]
 if target.startswith(('ms-settings:', 'windowsdefender:')):
  shell_open_windows(target)
 elif target.endswith('.msc'):
  shell_open_windows(str(system32 / 'mmc.exe'), f'"{system32 / target}"', elevate_if_required=True)
 elif target.endswith('.cpl'):
  shell_open_windows(str(system32 / 'control.exe'), f'"{system32 / target}"')
 elif tool == 'reliability':
  shell_open_windows(str(system32 / 'perfmon.exe'), '/rel')
 else:
  shell_open_windows(str(system32 / target), elevate_if_required=True)

import re

# Advanced actions are allowlisted, local-only, and never initiated by AI text.
def windows_edition():
 if os.name!='nt': return 'Unavailable'
 import winreg
 try:
  with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
   name=str(winreg.QueryValueEx(key,'ProductName')[0])
   # Windows 11 still reports "Windows 10" in ProductName; build 22000 and later is Windows 11.
   try:
    if int(winreg.QueryValueEx(key,'CurrentBuild')[0])>=22000:name=name.replace('Windows 10','Windows 11')
   except (OSError,ValueError):pass
   return name + ' (' + str(winreg.QueryValueEx(key,'EditionID')[0]) + ')'
 except OSError: return 'Unknown Windows edition'

def has_policy_editor():
 if os.name!='nt': return False
 import winreg
 try:
  with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
   edition=str(winreg.QueryValueEx(key,'EditionID')[0]).lower()
  return not any(x in edition for x in ('core','home'))
 except OSError: return False

def registry_lookup(root, path, value):
 import winreg
 roots={'HKLM':winreg.HKEY_LOCAL_MACHINE,'HKCU':winreg.HKEY_CURRENT_USER}
 if root not in roots or not isinstance(path,str) or len(path)>240 or not re.fullmatch(r'[A-Za-z0-9 _\\.{}()@+,-]+',path):
  raise ValueError('Invalid registry path')
 if not isinstance(value,str) or len(value)>120 or not re.fullmatch(r'[A-Za-z0-9 _.-]*',value):
  raise ValueError('Invalid registry value name')
 # Avoid huge binary dumps or arbitrary sensitive locations.
 blocked=('sam','security','system\\currentcontrolset\\control\\lsa','software\\microsoft\\credentials','software\\microsoft\\protected storage system provider')
 # ControlSet001/002 are the same data as CurrentControlSet, so check them under one name.
 normalized=re.sub(r'^system\\controlset\d{3}(?=\\|$)','system\\\\currentcontrolset',path.lower().strip('\\'))
 if any(normalized.startswith(x) for x in blocked):raise ValueError('Protected registry location')
 # Values such as Winlogon\DefaultPassword can hold credentials in plain text.
 if re.search(r'pass(word|wd)?|secret|credential|token',value,re.I):raise ValueError('PC Medic does not read values that may contain passwords or secrets')
 try:
  with winreg.OpenKey(roots[root],path,0,winreg.KEY_READ) as key:
   data,kind=winreg.QueryValueEx(key,value)
 except FileNotFoundError:raise ValueError('Registry key or value not found')
 if isinstance(data,bytes):return {'value':'(binary value not displayed)','type':kind}
 result=str(data)
 return {'value':result[:500] + ('…' if len(result)>500 else ''),'type':kind}

def launch_advanced(tool):
 if os.name != 'nt': raise RuntimeError('Windows only')
 system32 = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32'
 windir = system32.parent
 if tool in ('gpedit', 'secpol') and not has_policy_editor():
  raise ValueError('Not available on this Windows edition')
 if tool in ('gpedit', 'secpol'):
  policy = system32 / (tool + '.msc')
  if not policy.exists(): raise ValueError('Tool not installed')
  shell_open_windows(str(system32 / 'mmc.exe'), f'"{policy}"', elevate_if_required=True)
 elif tool == 'regedit':
  # Registry Editor lives in the Windows root, not System32.
  shell_open_windows(str(windir / 'regedit.exe'), elevate_if_required=True)
 elif tool == 'verifier':
  shell_open_windows(str(system32 / 'verifier.exe'), elevate_if_required=True)
 elif tool == 'wpr':
  # Show help only. Never begin a trace automatically.
  shell_open_windows(str(system32 / 'cmd.exe'), '/k wpr -help')
 else:
  raise ValueError('Unknown advanced tool')

def export_registry():
 # Export only HKCU Software PC Medic's own configuration scope, not entire registry.
 # Registry Editor's File > Export is preferable for full exports and requires user choice.
 raise ValueError('Use Registry Editor > File > Export to select a specific key and safe destination')

def history_read():
 if not HISTORY.exists():return []
 try:
  data=json.loads(HISTORY.read_text(encoding='utf-8'))
  return data[-100:] if isinstance(data,list) else []
 except (ValueError,OSError):return []

def history_append(item):
 with HISTORY_LOCK:
  records=history_read()
  records.append(item)
  temp=HISTORY.with_suffix('.tmp')
  temp.write_text(json.dumps(records[-100:],ensure_ascii=False,indent=2),encoding='utf-8')
  temp.replace(HISTORY)

def safe_history_entry(body):
 # No raw event messages, file paths, process names, IPs, or API keys are persisted.
 stats=body.get('stats',{})
 if not isinstance(stats,dict):raise ValueError('Invalid metrics')
 clean={}
 for k in ('cpu_peak','memory_peak','disk_peak','memory_latest','c_free_pct'):
  v=stats.get(k)
  if v is not None:
   if isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<=v<=100:raise ValueError('Invalid metric')
   clean[k]=round(v,2)
 titles=body.get('finding_titles',[])
 if not isinstance(titles,list):raise ValueError('Invalid findings')
 # Counts only: no free-text diagnostic evidence stored.
 return {'at_utc':datetime.now(timezone.utc).isoformat(),'metrics':clean,
         'finding_count':min(max(int(body.get('finding_count',0)),0),1000),
         'event_window_hours':24,'performance_samples':min(max(int(body.get('performance_samples',0)),0),500)}

def disk_forecast(records):
 """Estimate C: free-space trend from local scan-history percentages; no disk writes."""
 from datetime import datetime
 points=[]
 for r in records:
  try:
   t=datetime.fromisoformat(r['at_utc'].replace('Z','+00:00')).timestamp()
   free=r.get('metrics',{}).get('c_free_pct')
   if isinstance(free,(int,float)) and not isinstance(free,bool) and 0<=free<=100:points.append((t,float(free)))
  except (ValueError,TypeError,KeyError,OverflowError):pass
 if len(points)<3:return {'status':'insufficient','message':'At least 3 health checks across 24 hours are needed for a forecast.'}
 points.sort()
 span=(points[-1][0]-points[0][0])/86400
 if span<1:return {'status':'insufficient','message':'Collect scans over at least 24 hours before forecasting.'}
 x=[(t-points[0][0])/86400 for t,_ in points];y=[v for _,v in points]
 mx=sum(x)/len(x);my=sum(y)/len(y);den=sum((v-mx)**2 for v in x)
 slope=sum((a-mx)*(b-my) for a,b in zip(x,y))/den if den else 0
 if slope>=-0.1:return {'status':'stable','message':'No reliable declining free-space trend detected.'}
 days=y[-1]/-slope
 if days>365:return {'status':'stable','message':'Free-space decline is too gradual for a useful short-term forecast.'}
 return {'status':'estimate','days_until_full':round(days),'free_pct':round(y[-1],1),'pct_points_per_day':round(slope,2),'message':'Rough linear estimate based on scan history, not a guarantee.'}

OTHER_ACCOUNT='This copy of PC Medic belongs to another Windows account signed in on this computer. Start PC Medic from your own account; it will use its own private address.'

class LocalServer(ThreadingHTTPServer):
 """Exclusive port: Windows' SO_REUSEADDR would let another account bind the same port and intercept requests."""
 allow_reuse_address=False
 def server_bind(self):
  if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
  super().server_bind()

def start_server(port,tries=10):
 """Bind the first free port from `port`, so a second account's copy does not collide with the first."""
 for candidate in range(port,port+tries):
  try:return LocalServer(('127.0.0.1',candidate),Handler)
  except OSError:continue
 raise OSError(f'No free port between {port} and {port+tries-1}')

class Handler(BaseHTTPRequestHandler):
 def local_origins(self):
  port=self.server.server_address[1]
  return (f'127.0.0.1:{port}',f'localhost:{port}')
 def foreign_request(self):
  """Why this request must be refused, or None. Blocks DNS rebinding and other Windows accounts."""
  # A hostile site resolved to 127.0.0.1 still sends its own Host and Origin.
  if self.headers.get('Host','').lower() not in self.local_origins():return 'Requests must come from PC Medic on this computer'
  origin=self.headers.get('Origin')
  if origin and origin.lower() not in tuple('http://'+x for x in self.local_origins()):return 'Requests must come from PC Medic on this computer'
  # On a shared PC every signed-in account can reach 127.0.0.1; only the account that started PC Medic may use it.
  if not local_security.same_user(self.client_address,self.server.server_address[1]):return OTHER_ACCOUNT
  return None
 def troubleshoot(self,step,body):
  """Guided troubleshooting steps. Measuring steps take the single diagnostic slot."""
  case_id=str(body.get('case_id') or '')
  owner=body.get('owner') if valid_owner(body.get('owner')) else 'default'
  try:
   if step=='start':
    problem=body.get('problem')
    if not isinstance(problem,str) or not problem.strip():raise ValueError('Describe the problem first')
    return self.send_json(troubleshooter.public(troubleshooter.start(problem)))
   if step in ('context','done'):
    busy=activity_conflict(owner,'troubleshoot',seconds=60)
    if busy:return self.send_json({'error':busy+' is already running in another PC Medic window. Wait for it to finish.'},409)
    try:
     case=troubleshooter.investigate(case_id,body.get('context'),self.server.demo) if step=='context' else troubleshooter.validate(case_id,self.server.demo)
    finally:release_activity(owner)
    return self.send_json(troubleshooter.public(case))
   if step=='next':return self.send_json(troubleshooter.public(troubleshooter.next_recommendation(case_id)))
   if step=='feedback':return self.send_json(troubleshooter.public(troubleshooter.feedback(case_id,body.get('feeling'))))
  except ValueError as exc:return self.send_json({'error':str(exc)},400)
  return self.send_json({'error':'Not found'},404)
 def refuse(self,reason):
  # Read the unread request body first; replying mid-upload makes Windows reset the connection,
  # so the caller would see "connection reset" instead of this message.
  try:
   n=int(self.headers.get('Content-Length','0') or 0)
   if 0<n<=1048576:self.rfile.read(n)
  except (ValueError,OSError):pass
  if urlparse(self.path).path=='/':
   page=f'<!doctype html><meta charset=utf-8><title>PC Medic</title><p style="font:16px system-ui;max-width:560px;margin:60px auto">{reason}</p>'.encode()
   self.send_response(403);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(page)));self.end_headers();return self.wfile.write(page)
  return self.send_json({'error':reason},403)
 def do_GET(self):
  reason=self.foreign_request()
  if reason:return self.refuse(reason)
  path=urlparse(self.path).path
  if path=='/': return self.send_file(BASE/'dashboard.html','text/html; charset=utf-8')
  if path=='/api/network-info':
   return self.send_json({'network':network_inventory()})
  if path=='/api/hardware-upgrade':
   try: return self.send_json({'hardware':hardware_inventory()})
   except Exception as exc: return self.send_json({'hardware':{'available':False,'reason':'Windows hardware collector encountered an error ('+type(exc).__name__+').'}},200)
  if path=='/api/assistant-status':
   info=settings.summary()
   return self.send_json({'configured':info['providers']['anthropic']['available'],'openai':info['providers']['openai']['available'],'model':assistant.MODEL,'trial':info['trial'],
                          'sources':{k:v['source'] for k,v in info['providers'].items()}})
  if path=='/api/settings':return self.send_json(settings.summary())
  if path=='/api/troubleshoot/history':return self.send_json({'cases':troubleshooter.history()})
  if path=='/api/troubleshoot/case':
   case=troubleshooter.get((parse_qs(urlparse(self.path).query).get('id') or [''])[0])
   return self.send_json(troubleshooter.public(case)) if case else self.send_json({'error':'Unknown case'},404)
  if path=='/api/update-check':return self.send_json(settings.check_for_update())
  if path=='/api/assistant/job':
   job=assistant.JOBS.get((parse_qs(urlparse(self.path).query).get('id') or [''])[0])
   return self.send_json(job) if job else self.send_json({'error':'Unknown or expired question'},404)
  if path=='/api/check':
   name=(parse_qs(urlparse(self.path).query).get('name') or [''])[0]
   if name not in system_checks.SCRIPTS:return self.send_json({'error':'Unknown check'},400)
   data=system_checks.check(name)
   return self.send_json({'name':name,'available':data.get('available',False),'summary':system_checks.describe(name,data)})
  if path=='/api/history':return self.send_json({'history':history_read()})
  if path=='/api/disk-forecast':return self.send_json({'forecast':disk_forecast(history_read())})
  if path=='/api/advanced-capabilities':return self.send_json({'edition':windows_edition(),'policy_available':has_policy_editor(),'windows':os.name=='nt'})
  if path=='/api/report':
   try:
    report=get_report(self.server.demo)
    return self.send_json({'report':report,'analysis':analyze(report),'demo':self.server.demo,'csrf':TOKEN})
   except (FileNotFoundError,ValueError,OSError,json.JSONDecodeError) as exc:return self.send_json({'error':str(exc),'csrf':TOKEN},404)
  return self.send_json({'error':'Not found'},404)
 def do_POST(self):
  path=urlparse(self.path).path
  reason=self.foreign_request()
  if reason:return self.refuse(reason)
  if self.headers.get('X-PC-Medic-Token')!=TOKEN: return self.send_json({'error':'Invalid request token'},403)
  try:
   n=int(self.headers.get('Content-Length','0'))
   limit=131072 if path=='/api/technician-report' else 32768 if path in ('/api/performance-summary','/api/ai-ask') else 4096
   if n<0 or n>limit: return self.send_json({'error':'Request too large'},413)
   body=json.loads(self.rfile.read(n) or b'{}')
   if not isinstance(body,dict): return self.send_json({'error':'Expected a JSON object'},400)
   if not isinstance(body,dict):raise ValueError('Invalid request')
  except (ValueError,json.JSONDecodeError):return self.send_json({'error':'Invalid JSON'},400)
  if path=='/api/activity':
   owner=body.get('owner')
   if not valid_owner(owner):return self.send_json({'error':'Invalid window id'},400)
   if body.get('action')=='end':
    release_activity(owner);return self.send_json({'released':True})
   kind=body.get('kind')
   if kind not in ACTIVITY_LABELS:return self.send_json({'error':'Unknown activity'},400)
   busy=activity_conflict(owner,kind)
   if busy:return self.send_json({'error':busy+' is already running in another PC Medic window. Wait for it to finish.'},409)
   return self.send_json({'claimed':kind,'lease_seconds':LEASE_SECONDS})
  if path in ('/api/scan','/api/performance-sample','/api/process-memory'):
   # The scan itself can take up to 180 seconds, so it extends the lease past that.
   busy=activity_conflict(body.get('owner'),seconds=240 if path=='/api/scan' else LEASE_SECONDS)
   if busy:return self.send_json({'error':busy+' is already running in another PC Medic window. Wait for it to finish.'},409)
  if path=='/api/disk-health':
   if self.server.demo or os.name!='nt':return self.send_json({'error':'Disk scan is available on Windows only'},403)
   from collector import powershell, COLLECTORS
   results={name:powershell(COLLECTORS[name],timeout=35) for name in ('storage_health','drive_reliability','disks')}
   return self.send_json({'checks':results,'read_only':True,'at_utc':datetime.now(timezone.utc).isoformat()})
  if path=='/api/history-save':
   if self.server.demo:return self.send_json({'error':'History disabled in demo'},403)
   try:
    history_append(safe_history_entry(body))
    return self.send_json({'saved':True})
   except (ValueError,TypeError,OSError) as exc:return self.send_json({'error':str(exc)},400)
  if path=='/api/advanced-lookup':
   if self.server.demo or os.name!='nt':return self.send_json({'error':'Windows only'},403)
   try:return self.send_json(registry_lookup(body.get('root'),body.get('path'),body.get('value','')))
   except (ValueError,OSError) as exc:return self.send_json({'error':str(exc)},400)
  if path=='/api/advanced-launch':
   if self.server.demo or os.name!='nt':return self.send_json({'error':'Windows only'},403)
   tool=body.get('tool')
   if tool not in ('regedit','verifier','wpr','gpedit','secpol'):return self.send_json({'error':'Unknown tool'},400)
   if body.get('approved') is not True or body.get('confirmed') is not True:return self.send_json({'error':'Two-step confirmation required'},403)
   if tool in ('verifier','wpr') and body.get('technician') is not True:return self.send_json({'error':'Technician mode required'},403)
   try:
    launch_advanced(tool)
    return self.send_json({'message':'Windows launch requested. No changes were made by PC Medic.'})
   except (ValueError,OSError,RuntimeError) as exc:return self.send_json({'error':str(exc)},400)
  if path in ('/api/open-optimize', '/api/windows-tool'):
   if self.server.demo or os.name!='nt':return self.send_json({'error':'Windows only; unavailable in demo'},403)
   tool='optimize' if path=='/api/open-optimize' else body.get('tool')
   # Strict allowlist: no executable paths or arguments are accepted from the browser.
   if not isinstance(tool,str) or tool not in WINDOWS_TOOLS:
    return self.send_json({'error':'Unknown Windows tool'},400)
   if body.get('approved') is not True:
    return self.send_json({'error':'User approval is required to open Windows tools'},403)
   if tool=='memory-diagnostic' and body.get('reboot_warning_acknowledged') is not True:
    return self.send_json({'error':'Memory Diagnostic may require a restart; acknowledge the warning first'},403)
   try:
    launch_windows_tool(tool)
    return self.send_json({'message':WINDOWS_TOOLS[tool][0]+' launch requested. No maintenance action was performed.'})
   except (OSError,RuntimeError) as exc:return self.send_json({'error':str(exc)},500)
  if path=='/api/devices':
   try:return self.send_json(device_inventory(demo=self.server.demo))
   except (RuntimeError,subprocess.TimeoutExpired) as exc:return self.send_json({'error':str(exc)},500)
  if path=='/api/storage-search':
   if self.server.demo:return self.send_json({'error':'Storage Explorer unavailable in demo mode'},403)
   owner=body.get('owner') if valid_owner(body.get('owner')) else 'default'
   # A search reads the disk for up to 40 seconds, so it takes the single diagnostic slot like a scan.
   busy=activity_conflict(owner,'storage',seconds=60)
   if busy:return self.send_json({'error':busy+' is already running in another PC Medic window. Wait for it to finish.'},409)
   try:return self.send_json(inventory(body.get('minimum_mb',100),body.get('category','all'),body.get('scope','profile'),owner))
   except (RuntimeError,ValueError,OSError) as exc:return self.send_json({'error':str(exc)},400)
   finally:release_activity(owner)
  if path=='/api/storage-recycle':
   if self.server.demo:return self.send_json({'error':'Storage Explorer unavailable in demo mode'},403)
   try:
    if not isinstance(body.get('id'),str):raise ValueError('Invalid selection')
    if body.get('approved') is not True:raise ValueError('File-specific approval is required')
    return self.send_json(recycle(body['id'],body.get('owner') if valid_owner(body.get('owner')) else 'default'))
   except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired) as exc:return self.send_json({'error':str(exc)},400)
  if path=='/api/ai-ask':
   question=body.get('question','');provider=body.get('provider','');consent=body.get('consent')
   if consent is not True:return self.send_json({'error':'Explicit data-sharing consent required'},403)
   if not isinstance(question,str) or not 1<=len(question.strip())<=500:return self.send_json({'error':'Question must be 1–500 characters'},400)
   # Claude questions go to /api/assistant; this endpoint is the ChatGPT fallback.
   if provider!='openai':return self.send_json({'error':'Use the Claude assistant for Claude questions'},400)
   try:
    investigation=body.get('investigation')
    try: current_report=get_report(self.server.demo)
    except FileNotFoundError: current_report=watch_only_report(investigation)
    result=ai_ask(provider,question,current_report,self.server.demo,body.get('tool_approved') is True,investigation)
    return self.send_json(result)
   except (RuntimeError,ValueError,OSError) as exc:return self.send_json({'error':str(exc)},502)
  if path=='/api/technician-report':
   turns=body.get('conversation')
   if turns is not None and not isinstance(turns,list):return self.send_json({'error':'Invalid conversation'},400)
   try:scan=get_report(self.server.demo)
   except (FileNotFoundError,ValueError,OSError,json.JSONDecodeError):scan=None
   content=tech_report.generate(scan,turns).encode('utf-8')
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
   return self.wfile.write(content)
  if path=='/api/assistant':
   if body.get('consent') is not True:return self.send_json({'error':'Approval to share data with Claude is required'},403)
   question=body.get('question','')
   if not isinstance(question,str) or not 1<=len(question.strip())<=1000:return self.send_json({'error':'Question must be 1–1000 characters'},400)
   try:key,_=settings.key_for_use('anthropic')
   except settings.TrialExhausted as exc:return self.send_json({'error':str(exc),'trial_exhausted':True},402)
   if not key:return self.send_json({'error':'Claude is not set up on this PC. Add an Anthropic key in Settings.'},503)
   conv=body.get('conversation_id')
   # Runs in the background; the page polls /api/assistant/job for progress and the answer.
   return self.send_json({'job_id':assistant.JOBS.start(conv if isinstance(conv,str) and len(conv)<=40 else None,question.strip(),self.server.demo)})
  if path.startswith('/api/troubleshoot/'):
   return self.troubleshoot(path.rsplit('/',1)[-1],body)
  if path=='/api/assistant/cancel':
   return self.send_json({'cancelling':assistant.JOBS.cancel(str(body.get('job_id','')))})
  if path=='/api/settings/key':
   provider,key=body.get('provider'),str(body.get('key') or '').strip()
   if provider not in settings.PROVIDERS:return self.send_json({'error':'Unknown provider'},400)
   if os.name!='nt':return self.send_json({'error':'Saving keys needs Windows Credential Manager'},400)
   try:
    settings.verify_key(provider,key)
    settings.save_key(provider,key)
   except (ValueError,RuntimeError,OSError) as exc:return self.send_json({'error':str(exc)},400)
   return self.send_json({'saved':True,'settings':settings.summary()})
  if path=='/api/settings/key-remove':
   if body.get('provider') not in settings.PROVIDERS:return self.send_json({'error':'Unknown provider'},400)
   settings.delete_key(body['provider'])
   return self.send_json({'removed':True,'settings':settings.summary()})
  if path=='/api/settings/updates':
   settings.set_update_checks(body.get('enabled') is True)
   return self.send_json({'settings':settings.summary()})
  if path in ('/api/parts-research','/api/parts-research-preview'):
   fields={k:body.get(k,'') for k in ('kind','manufacturer','model','product_name','part_number','details')}
   try:
    if path=='/api/parts-research-preview':return self.send_json(parts_preview(**fields))
    if body.get('approved') is not True:return self.send_json({'error':'Explicit online research approval required'},403)
    return self.send_json(parts_research(**fields))
   except ValueError as exc:return self.send_json({'error':str(exc)},400)
   except Exception as exc:return self.send_json({'error':'Online research could not complete ('+type(exc).__name__+')'},502)
  if path=='/api/intent':
   question=body.get('question','')
   if not isinstance(question,str) or len(question)>1500:return self.send_json({'error':'Invalid question'},400)
   return self.send_json(classify_intent(question,body.get('context')))
  if path=='/api/performance-sample':
   try:return self.send_json(collect_performance(demo=self.server.demo))
   except (RuntimeError,subprocess.TimeoutExpired) as exc:return self.send_json({'error':str(exc)},500)
  if path=='/api/performance-summary':
   try:return self.send_json(summarize(body.get('samples')))
   except (ValueError,TypeError) as exc:return self.send_json({'error':str(exc)},400)
  if path=='/api/process-memory':
   try: return self.send_json(collect_processes(demo=self.server.demo))
   except (RuntimeError,subprocess.TimeoutExpired) as exc:return self.send_json({'error':str(exc)},500)
  if path=='/api/scan':
   if self.server.demo:return self.send_json({'error':'Demo mode cannot scan your computer'},403)
   if os.name!='nt':return self.send_json({'error':'Windows scanning is only supported on Windows'},400)
   if not LOCK.acquire(blocking=False):return self.send_json({'error':'Scan already running'},409)
   try:
    # Fixed allowlisted script, fixed output path, no shell or user-controlled command.
    result=subprocess.run(collector_command(),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,check=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:return self.send_json({'error':'Collector failed','details':result.stderr[-500:]},500)
    report=get_report(False)
    return self.send_json({'report':report,'analysis':analyze(report),'demo':False,'csrf':TOKEN})
   except subprocess.TimeoutExpired:return self.send_json({'error':'Scan timed out after 180 seconds'},504)
   finally:LOCK.release()
  return self.send_json({'error':'Not found'},404)
 def send_file(self,path,content_type):
  content=path.read_bytes();self.send_response(200);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(content)
 def send_json(self,obj,status=200):
  content=json.dumps(obj,default=str).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(content)

def load_saved_keys(names=('ANTHROPIC_API_KEY','OPENAI_API_KEY')):
 """Pick up API keys saved with setx after this window opened (HKCU\\Environment). Values are never logged."""
 if os.name!='nt':return
 import winreg
 try:
  with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
   for name in names:
    if os.environ.get(name,'').strip():continue
    try:
     value=str(winreg.QueryValueEx(key,name)[0]).strip()
     if value:os.environ[name]=value
    except FileNotFoundError:pass
 except OSError:pass

def collector_command():
 """In a packaged .exe sys.executable is PC Medic itself, so it re-enters main() in collector mode."""
 if FROZEN:return [sys.executable,'--run-collector','--output',str(SCAN)]
 return [sys.executable,str(BASE/'collector.py'),'--output',str(SCAN)]

def main():
 if len(sys.argv)>1 and sys.argv[1]=='--run-collector':
  import collector
  sys.argv=[sys.argv[0]]+sys.argv[2:]
  return collector.main()
 p=argparse.ArgumentParser();p.add_argument('--demo',action='store_true');p.add_argument('--port',type=int,default=8765)
 p.add_argument('--ignore-env-keys',action='store_true',help='Ignore ANTHROPIC_API_KEY/OPENAI_API_KEY, to test Settings and the trial as a new user')
 a=p.parse_args()
 if a.ignore_env_keys:settings.IGNORE_ENVIRONMENT=True;print('Ignoring API keys from the environment (testing Settings and the trial).',flush=True)
 else:load_saved_keys()
 server=start_server(a.port);server.demo=a.demo
 port=server.server_address[1]
 if port!=a.port:print(f'Port {a.port} is in use (perhaps PC Medic in another Windows account), so this copy uses {port}.',flush=True)
 print(f'PC Medic AI {VERSION}: http://127.0.0.1:{port} ({"SIMULATED DEMO" if a.demo else "LOCAL SCAN"})',flush=True)
 print('Diagnostics are read-only. Storage Explorer can move explicitly selected personal files to Recycle Bin. Ctrl+C to stop.',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
if __name__=='__main__':main()
