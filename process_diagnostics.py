"""Read-only Windows process memory sampling; no process arguments or user paths."""
import json, os, subprocess
from datetime import datetime, timezone

DEMO_PROCESSES = [
 {"name":"Browser.exe","pid":4100,"working_set_mb":2850.0},
 {"name":"Editor.exe","pid":4220,"working_set_mb":1120.0},
 {"name":"VideoCall.exe","pid":4300,"working_set_mb":750.0},
]

def collect_processes(demo=False):
 if demo:
  rows=DEMO_PROCESSES
 elif os.name!='nt':
  raise RuntimeError('Process sampling is supported on Windows only')
 else:
  # PowerShell is invoked without shell=True; script is fixed and read-only.
  script = ("Get-CimInstance Win32_Process | "
            "Select-Object Name,ProcessId,WorkingSetSize | "
            "ConvertTo-Json -Compress -Depth 3")
  proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command','[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);'+script],
    capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35,check=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if proc.returncode:
   raise RuntimeError('Windows process collection failed: '+proc.stderr[-200:])
  try: raw=json.loads(proc.stdout.strip() or '[]')
  except json.JSONDecodeError as exc: raise RuntimeError('Invalid process collector output') from exc
  if isinstance(raw,dict):raw=[raw]
  rows=[]
  for x in raw:
   if not isinstance(x,dict):continue
   try:
    name=str(x.get('Name') or 'Unknown')[:100]
    pid=int(x.get('ProcessId') or 0)
    mb=round(int(x.get('WorkingSetSize') or 0)/1048576,1)
    if pid>=0 and mb>=0:rows.append({'name':name,'pid':pid,'working_set_mb':mb})
   except (ValueError,TypeError):continue
 rows=sorted(rows,key=lambda x:x['working_set_mb'],reverse=True)[:12]
 return {'sampled_at_utc':datetime.now(timezone.utc).isoformat(),
         'metric':'Working set (physical memory resident at sample time)',
         'processes':rows,
         'note':'Working sets can include shared memory. Values are snapshots and do not add up to total physical memory usage. Process names and PIDs may reveal installed software.'}
