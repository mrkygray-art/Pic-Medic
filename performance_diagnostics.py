"""Read-only, fixed-command Windows performance sampling."""
import json,os,subprocess
from datetime import datetime,timezone

def parse_metrics(raw):
    if not isinstance(raw,dict): raise ValueError('Invalid performance sample')
    def num(name):
        try:
            v=float(raw.get(name))
            return round(v,2) if 0<=v<=1000000 else None
        except (TypeError,ValueError,OverflowError):return None
    total=num('total_mb');available=num('available_mb')
    # '% Disk Time' exceeds 100 on fast or multi-queue drives; busy = 100 - '% Idle Time' stays within 0-100.
    idle=num('disk_idle_percent')
    busy=round(max(0.0,100-min(idle,100)),2) if idle is not None else num('disk_busy_percent')
    if busy is not None:busy=min(busy,100.0)
    return {'sampled_at_utc':datetime.now(timezone.utc).isoformat(),
            'cpu_percent':num('cpu_percent'), 'memory_total_mb':total,
            'memory_available_mb':available,
            'memory_used_percent':round(100*(total-available)/total,2) if total and available is not None and available<=total else None,
            'disk_busy_percent':busy,
            'disk_queue_length':num('disk_queue_length'),
            'note':'Read-only system counters. Disk activity is an instantaneous sample; counter availability varies by Windows installation.'}

COUNTERS = {'cpu_percent': r'\Processor(_Total)\% Processor Time',
            'disk_idle_percent': r'\PhysicalDisk(_Total)\% Idle Time',
            'disk_queue_length': r'\PhysicalDisk(_Total)\Current Disk Queue Length'}

def sample_counters(interval=1.0):
    """Read CPU and disk counters in-process with PDH. Starting PowerShell for every sample added its own CPU load
    to the reading. English counter names work on every Windows language."""
    import ctypes, time
    from ctypes import wintypes
    pdh, k32 = ctypes.WinDLL('pdh'), ctypes.WinDLL('kernel32')
    class Value(ctypes.Structure):
        _fields_ = [('CStatus', wintypes.DWORD), ('doubleValue', ctypes.c_double)]
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('dwLength', wintypes.DWORD), ('dwMemoryLoad', wintypes.DWORD), ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong), ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    query = ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)):raise OSError('PDH unavailable')
    try:
        handles = {}
        for name, path in COUNTERS.items():
            handle = ctypes.c_void_p()
            if pdh.PdhAddEnglishCounterW(query, path, None, ctypes.byref(handle)) == 0:handles[name] = handle
        if 'cpu_percent' not in handles:raise OSError('Processor counter unavailable')
        pdh.PdhCollectQueryData(query)
        time.sleep(interval)  # rate counters need two readings
        if pdh.PdhCollectQueryData(query):raise OSError('PDH collection failed')
        raw = {}
        for name, handle in handles.items():
            value = Value()
            if pdh.PdhGetFormattedCounterValue(handle, 0x200, None, ctypes.byref(value)) == 0:raw[name] = value.doubleValue  # PDH_FMT_DOUBLE
    finally:
        pdh.PdhCloseQuery(query)
    memory = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
    if k32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raw['total_mb'], raw['available_mb'] = memory.ullTotalPhys / 1048576, memory.ullAvailPhys / 1048576
    return raw

def collect_performance(demo=False):
    if demo:
        return parse_metrics({'cpu_percent':34,'total_mb':16384,'available_mb':5600,'disk_busy_percent':12,'disk_queue_length':0.2})
    if os.name!='nt':raise RuntimeError('Performance sampling requires Windows')
    try:return parse_metrics(sample_counters())
    except OSError:pass  # fall back to PowerShell below
    # No user-controlled shell text. Fixed CIM queries and selected numeric fields only.
    script=r"""$ErrorActionPreference='Stop';
$c=Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'";
$m=Get-CimInstance Win32_OperatingSystem;
$d=Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'";
[pscustomobject]@{cpu_percent=$c.PercentProcessorTime;total_mb=[math]::Round($m.TotalVisibleMemorySize/1024,2);available_mb=[math]::Round($m.FreePhysicalMemory/1024,2);disk_busy_percent=$d.PercentDiskTime;disk_idle_percent=$d.PercentIdleTime;disk_queue_length=$d.CurrentDiskQueueLength}|ConvertTo-Json -Compress"""
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,check=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:raise RuntimeError('Windows performance counters unavailable; try restarting PC Medic')
    try:return parse_metrics(json.loads(p.stdout.strip()))
    except (json.JSONDecodeError,ValueError) as e:raise RuntimeError('Invalid Windows performance data') from e

def summarize(samples):
    if not isinstance(samples,list) or not 2<=len(samples)<=60:raise ValueError('Need 2–60 performance samples')
    fields=('cpu_percent','memory_used_percent','disk_busy_percent','disk_queue_length')
    stats={}
    for field in fields:
        values=[float(x[field]) for x in samples if isinstance(x,dict) and isinstance(x.get(field),(int,float))]
        stats[field]={'min':round(min(values),2),'max':round(max(values),2),'average':round(sum(values)/len(values),2),'last':round(values[-1],2)} if values else None
    return {'sample_count':len(samples),'first_sample_utc':samples[0].get('sampled_at_utc'),
            'last_sample_utc':samples[-1].get('sampled_at_utc'),'stats':stats,
            'limitations':'Samples are not continuous. CPU and disk spikes between samples may be missed. Disk busy counter can exceed 100 on some systems; do not infer disk failure. No process attribution or memory-leak diagnosis.'}
