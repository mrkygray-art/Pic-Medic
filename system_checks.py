"""Read-only Windows checks: battery, disk health, crashes, updates, startup apps, pending reboot, listening ports.

Each check returns {'available': bool, ...data}. describe() turns data into plain English for the
offline assistant; for_cloud() strips anything identifying before Claude sees it.
"""
import json, os, re, subprocess

HEADER = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)\n$ErrorActionPreference='SilentlyContinue'\n"

def run(script, timeout=30):
    if os.name != 'nt':return {'available':False,'reason':'This check requires Windows.'}
    try:
        p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',HEADER+script],capture_output=True,text=True,
                         encoding='utf-8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        data=json.loads(p.stdout.lstrip('﻿').strip() or 'null')
        if not isinstance(data,dict):return {'available':False,'reason':'Windows returned no data for this check.'}
        data['available']=True
        return data
    except subprocess.TimeoutExpired:return {'available':False,'reason':'The check timed out.'}
    except (OSError,ValueError):return {'available':False,'reason':'Windows could not run this check.'}

def as_list(value):
    return value if isinstance(value,list) else [] if value is None else [value]

BATTERY = r'''
$b=@(Get-CimInstance Win32_Battery)
if(-not $b){[pscustomobject]@{Present=$false}|ConvertTo-Json -Compress;return}
$f=Join-Path $env:TEMP ('pcmedic-battery-'+[guid]::NewGuid().ToString()+'.xml')
powercfg /batteryreport /xml /output $f | Out-Null
$design=$null;$full=$null;$cycles=$null;$chem=$null
if(Test-Path $f){[xml]$x=Get-Content $f -Raw;Remove-Item $f -Force
 $bat=@($x.BatteryReport.Batteries.Battery)[0];$design=[int64]$bat.DesignCapacity;$full=[int64]$bat.FullChargeCapacity;$cycles=[int]$bat.CycleCount;$chem=[string]$bat.Chemistry}
[pscustomobject]@{Present=$true;Model=$b[0].Name;ChargePercent=$b[0].EstimatedChargeRemaining;OnAC=($b[0].BatteryStatus -eq 2);DesignCapacity_mWh=$design;FullChargeCapacity_mWh=$full;CycleCount=$cycles;Chemistry=$chem}|ConvertTo-Json -Compress
'''

DISK = r'''
$disks=@(Get-PhysicalDisk | ForEach-Object { $d=$_; $r=$d | Get-StorageReliabilityCounter
 [pscustomobject]@{Name=$d.FriendlyName;MediaType=[string]$d.MediaType;BusType=[string]$d.BusType;SizeGB=[math]::Round($d.Size/1GB);Health=[string]$d.HealthStatus;Status=[string]$d.OperationalStatus;
  TemperatureC=$r.Temperature;WearPercent=$r.Wear;PowerOnHours=$r.PowerOnHours;ReadErrorsUncorrected=$r.ReadErrorsUncorrected;WriteErrorsUncorrected=$r.WriteErrorsUncorrected} })
$vols=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {[pscustomobject]@{Drive=$_.DeviceID;SizeGB=[math]::Round($_.Size/1GB,1);FreeGB=[math]::Round($_.FreeSpace/1GB,1)}})
[pscustomobject]@{Disks=$disks;Volumes=$vols}|ConvertTo-Json -Depth 4 -Compress
'''

CRASHES = r'''
$since=(Get-Date).AddDays(-30)
function Get-Ev($id,$provider){@(Get-WinEvent -FilterHashtable @{LogName='System';Id=$id;ProviderName=$provider;StartTime=$since} -MaxEvents 50)}
$bsod=@(Get-Ev 1001 'Microsoft-Windows-WER-SystemErrorReporting' | ForEach-Object {[pscustomobject]@{Date=$_.TimeCreated.ToString('s');Code=([regex]::Match($_.Message,'0x[0-9A-Fa-f]{8}')).Value}})
$power=@(Get-Ev 41 'Microsoft-Windows-Kernel-Power' | ForEach-Object {$_.TimeCreated.ToString('s')})
$dirty=@(Get-Ev 6008 'EventLog').Count
$dumps=@(Get-ChildItem (Join-Path $env:SystemRoot 'Minidump') -Filter *.dmp | Sort-Object LastWriteTime -Descending)
[pscustomobject]@{WindowDays=30;BlueScreens=$bsod;UnexpectedRestarts=$power;DirtyShutdowns=$dirty;MinidumpCount=$dumps.Count;LatestMinidump=$(if($dumps){$dumps[0].LastWriteTime.ToString('s')}else{$null})}|ConvertTo-Json -Depth 4 -Compress
'''

UPDATES = r'''
$since=(Get-Date).AddDays(-30)
$ev=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WindowsUpdateClient';Id=19,20;StartTime=$since} -MaxEvents 300)
$fail=@($ev | Where-Object Id -eq 20 | Select-Object -First 15 | ForEach-Object { $m=[regex]::Match($_.Message,'error (0x[0-9A-Fa-f]+):\s*(.+?)\.?\s*$')
 [pscustomobject]@{Date=$_.TimeCreated.ToString('s');Error=$m.Groups[1].Value;Update=$m.Groups[2].Value} })
$ok=@($ev | Where-Object Id -eq 19)
[pscustomobject]@{WindowDays=30;Failures=$fail;FailureCount=@($ev | Where-Object Id -eq 20).Count;SuccessCount=$ok.Count;LastSuccess=$(if($ok){$ok[0].TimeCreated.ToString('s')}else{$null})}|ConvertTo-Json -Depth 4 -Compress
'''

# Only the app name and whether it starts for all users; command paths and user names are not collected.
STARTUP = r'''
$apps=@(Get-CimInstance Win32_StartupCommand | ForEach-Object {[pscustomobject]@{Name=$_.Name;Scope=$(if($_.User -match 'Public|NT AUTHORITY|\.DEFAULT|All Users'){'All users'}else{'This user'});Source=$(if($_.Location -match 'Startup'){'Startup folder'}else{'Registry'})}} | Sort-Object Name -Unique)
[pscustomobject]@{Apps=$apps;Count=$apps.Count}|ConvertTo-Json -Depth 3 -Compress
'''

REBOOT = r'''
$os=Get-CimInstance Win32_OperatingSystem
$rename=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations).PendingFileRenameOperations
[pscustomobject]@{ComponentServicing=(Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending');
 WindowsUpdate=(Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired');
 PendingFileRename=[bool]$rename;LastBoot=$os.LastBootUpTime.ToString('s');UptimeDays=[math]::Round(((Get-Date)-$os.LastBootUpTime).TotalDays,1)}|ConvertTo-Json -Compress
'''

PORTS = r'''
$names=@{};Get-Process | ForEach-Object {$names[$_.Id]=$_.ProcessName}
$tcp=@(Get-NetTCPConnection -State Listen | Sort-Object LocalPort,LocalAddress -Unique | Select-Object -First 80 | ForEach-Object {
 [pscustomobject]@{Port=$_.LocalPort;LocalOnly=($_.LocalAddress -in '127.0.0.1','::1');Process=$names[[int]$_.OwningProcess]}})
[pscustomobject]@{Tcp=$tcp;UdpCount=@(Get-NetUDPEndpoint).Count}|ConvertTo-Json -Depth 3 -Compress
'''

SCRIPTS = {'battery':(BATTERY,40),'disk_health':(DISK,30),'crashes':(CRASHES,40),'updates':(UPDATES,40),
           'startup_apps':(STARTUP,25),'pending_reboot':(REBOOT,20),'listening_ports':(PORTS,25)}
TITLES = {'battery':'Battery health','disk_health':'Disk health','crashes':'Crashes and unexpected restarts (last 30 days)',
          'updates':'Windows Update history (last 30 days)','startup_apps':'Startup apps','pending_reboot':'Pending restart',
          'listening_ports':'Network ports listening for connections'}
WELL_KNOWN = {7680:'Delivery Optimization (update sharing)',135:'RPC',139:'NetBIOS',445:'File sharing (SMB)',3389:'Remote Desktop',5357:'Network discovery',5040:'Windows service',
              80:'Web server',443:'Web server (HTTPS)',22:'SSH',21:'FTP',3306:'MySQL',1433:'SQL Server',5432:'PostgreSQL',8080:'Web server'}

def check(name):
    if name not in SCRIPTS:raise ValueError('Unknown check')
    script,timeout=SCRIPTS[name]
    data=run(script,timeout)
    if name=='battery' and data.get('available') and data.get('Present'):
        design,full=data.get('DesignCapacity_mWh'),data.get('FullChargeCapacity_mWh')
        data['HealthPercent']=round(100*full/design) if isinstance(design,int) and isinstance(full,int) and design>0 else None
    return data

def describe(name, d):
    """Plain-English summary of a check for the offline assistant."""
    if not d.get('available'):return f'{TITLES[name]}: unavailable. {d.get("reason","")}'.strip()
    lines=[]
    if name=='battery':
        if not d.get('Present'):return 'Battery health: no battery detected. This looks like a desktop or a server.'
        health=d.get('HealthPercent')
        lines.append(f'Battery {d.get("Model") or ""}: {d.get("ChargePercent")}% charged{", plugged in" if d.get("OnAC") else ", on battery"}.')
        if health is not None:
            lines.append(f'It now holds {d["FullChargeCapacity_mWh"]:,} mWh of its original {d["DesignCapacity_mWh"]:,} mWh design capacity, about {health}% of new.')
            lines.append('That is healthy.' if health>=80 else 'That is noticeable wear: expect shorter battery life.' if health>=60 else 'That is heavy wear. A replacement battery would restore battery life.')
        if d.get('CycleCount'):lines.append(f'Charge cycles reported: {d["CycleCount"]}.')
    elif name=='disk_health':
        for disk in as_list(d.get('Disks')):
            bits=[f'{disk.get("Name")} ({disk.get("MediaType") or "disk"}, {disk.get("SizeGB")} GB): health status {disk.get("Health") or "unknown"}']
            if disk.get('TemperatureC'):bits.append(f'{disk["TemperatureC"]}°C')
            if disk.get('WearPercent') is not None:bits.append(f'{disk["WearPercent"]}% wear used')
            if disk.get('PowerOnHours'):bits.append(f'{disk["PowerOnHours"]:,} hours powered on')
            errors=(disk.get('ReadErrorsUncorrected') or 0)+(disk.get('WriteErrorsUncorrected') or 0)
            if errors:bits.append(f'{errors} uncorrected read/write errors (back up your files)')
            lines.append(', '.join(bits)+'.')
        for v in as_list(d.get('Volumes')):
            lines.append(f'{v.get("Drive")} drive: {v.get("FreeGB")} GB free of {v.get("SizeGB")} GB.')
        if not any(x.get('WearPercent') is not None or x.get('TemperatureC') for x in as_list(d.get('Disks'))):
            lines.append('Detailed SMART counters (wear, temperature) need PC Medic to run as administrator or are not exposed by this drive.')
    elif name=='crashes':
        bsod=as_list(d.get('BlueScreens'));restarts=as_list(d.get('UnexpectedRestarts'))
        lines.append(f'Blue screens: {len(bsod)}.'+(' Stop codes: '+', '.join(sorted({b.get("Code") for b in bsod if b.get("Code")}))+'.' if bsod else ''))
        lines.append(f'Unexpected restarts or power losses: {len(restarts)}. Improper shutdowns: {d.get("DirtyShutdowns",0)}.')
        if d.get('MinidumpCount'):lines.append(f'Crash dump files saved: {d["MinidumpCount"]} (latest {d.get("LatestMinidump","")[:10]}).')
        if not bsod and not restarts:lines.append('No crashes recorded in the last 30 days.')
        elif bsod:lines.append('A repeating stop code usually points to a specific driver or hardware fault. Search the code on Microsoft Learn, or ask Claude to interpret it.')
        else:lines.append('Unexpected restarts without a blue screen often mean power loss, a held power button, overheating or a hard freeze.')
    elif name=='updates':
        lines.append(f'Successful installs: {d.get("SuccessCount",0)}. Failed installs: {d.get("FailureCount",0)}.'+(f' Last success: {str(d.get("LastSuccess"))[:10]}.' if d.get('LastSuccess') else ''))
        for f in as_list(d.get('Failures'))[:5]:
            update=re.sub(r'^[0-9A-Z]{12}-','Microsoft Store app ',f.get('Update') or 'unknown update')  # Store product IDs mean nothing to people
            lines.append(f'Failed {str(f.get("Date"))[:10]}: {update} (error {f.get("Error") or "unknown"}).')
        if any(f.get('Error')=='0x80073D02' for f in as_list(d.get('Failures'))):lines.append('Error 0x80073D02 means a Store app was open during its update; it usually succeeds on a later try.')
        if d.get('FailureCount'):lines.append('If the same update keeps failing, run Windows Update troubleshooter (Settings > System > Troubleshoot) and search the error code.')
    elif name=='startup_apps':
        apps=as_list(d.get('Apps'))
        names=[re.sub(r'_[0-9A-F]{32}$','',a.get('Name','')) for a in apps]  # Edge adds a profile hash
        lines.append(f'{len(apps)} apps start automatically when you sign in.'+(' '+', '.join(names[:15])+'.' if apps else ''))
        lines.append('Disable the ones you do not need in Task Manager > Startup apps. Some listed apps may already be disabled there.')
    elif name=='pending_reboot':
        pending=[label for key,label in (('ComponentServicing','Windows component updates'),('WindowsUpdate','Windows Update')) if d.get(key)]
        lines.append(('A restart is pending for: '+', '.join(pending)+'.') if pending else 'No Windows restart is pending.')
        if d.get('PendingFileRename') and not pending:lines.append('Some files are queued to be replaced at the next restart (common after installing software).')
        lines.append(f'Last restart: {str(d.get("LastBoot"))[:10]} ({d.get("UptimeDays")} days ago).'+(' Restarting regularly helps updates finish and frees memory.' if (d.get('UptimeDays') or 0)>=7 else ''))
    elif name=='listening_ports':
        tcp=list({(t.get('Port'),t.get('LocalOnly')):t for t in as_list(d.get('Tcp'))}.values())  # IPv4 and IPv6 listeners on the same port
        exposed=[t for t in tcp if not t.get('LocalOnly')];dynamic=[t for t in exposed if (t.get('Port') or 0)>=49152]
        lines.append(f'{len(tcp)} TCP ports are listening; {len(exposed)} accept connections from the network and {len(tcp)-len(exposed)} only from this PC. UDP endpoints: {d.get("UdpCount",0)}.')
        for t in [t for t in exposed if t not in dynamic][:12]:
            label=' · '.join(x for x in (WELL_KNOWN.get(t.get('Port')),t.get('Process')) if x)
            lines.append(f'Port {t.get("Port")}'+(f': {label}' if label else ''))
        if dynamic:lines.append(f'Plus {len(dynamic)} high-numbered ports (49152+), normally Windows services using dynamic ports.')
        lines.append('Physical ports (USB, HDMI) cannot be counted from Windows; check the manufacturer specifications for your model.')
    return TITLES[name]+':\n'+'\n'.join(lines)

def for_cloud(name, d):
    """Data Claude may see: no serials, user names, paths, process names, IPs or MACs."""
    if not d.get('available'):return {'available':False,'reason':d.get('reason')}
    d=json.loads(json.dumps(d))
    if name=='listening_ports':
        unique={(t.get('Port'),t.get('LocalOnly')):t for t in as_list(d.get('Tcp'))}.values()
        d['Tcp']=[{'Port':t.get('Port'),'LocalOnly':t.get('LocalOnly'),'Service':WELL_KNOWN.get(t.get('Port'))} for t in unique]
    if name=='startup_apps':
        apps=as_list(d.pop('Apps',None))
        d['AllUsers']=sum(a.get('Scope')=='All users' for a in apps);d['ThisUser']=len(apps)-d['AllUsers']
    if name=='battery':d.pop('Model',None)
    return d
