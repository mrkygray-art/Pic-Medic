"""Read-only Windows checks: battery, disk health, crashes, updates, startup apps, pending reboot, listening ports, security.

Each check returns {'available': bool, ...data}. describe() turns data into plain English for the
offline assistant; for_cloud() strips anything identifying before Claude sees it.
"""
import json, os, re, subprocess
from datetime import datetime, date

import bluescreen
import error_codes

DEEP_SCAN_FILE = None  # set by dashboard.py; the latest administrator deep scan (deep_scan.py), if any

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
 $bat=@($x.BatteryReport.Batteries.Battery)[0];$design=[int64]$bat.DesignCapacity;$full=[int64]$bat.FullChargeCapacity;$cycles=[int]$bat.CycleCount;$chem=[string]$bat.Chemistry
 $rt=$x.BatteryReport.RuntimeEstimates;$runFull=[string]$rt.FullChargeCapacity.ActiveRuntime;$runDesign=[string]$rt.DesignCapacity.ActiveRuntime
 # Capacity history since the last battery swap, thinned to about 12 points (date + full-charge capacity only)
 $h=@($x.BatteryReport.History.HistoryEntry | Where-Object {[int64]$_.FullChargeCapacity -gt 0})
 for($i=$h.Count-1;$i -gt 0;$i--){if($h[$i].BatteryChanged -eq '1'){$h=$h[$i..($h.Count-1)];break}}
 if($h.Count){$step=[math]::Max(1,[math]::Ceiling($h.Count/12));$idx=@(for($i=0;$i -lt $h.Count;$i+=$step){$i});if($idx[-1] -ne $h.Count-1){$idx+=$h.Count-1}
  $hist=@($idx|ForEach-Object{[pscustomobject]@{Date=([string]$h[$_].LocalStartDate).Substring(0,10);Full_mWh=[int64]$h[$_].FullChargeCapacity}})}}
[pscustomobject]@{Present=$true;Model=$b[0].Name;ChargePercent=$b[0].EstimatedChargeRemaining;OnAC=($b[0].BatteryStatus -eq 2);DesignCapacity_mWh=$design;FullChargeCapacity_mWh=$full;CycleCount=$cycles;Chemistry=$chem;RuntimeFull=$runFull;RuntimeDesign=$runDesign;History=$hist}|ConvertTo-Json -Compress -Depth 4
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
$bsod=@(Get-Ev 1001 'Microsoft-Windows-WER-SystemErrorReporting' | ForEach-Object {[pscustomobject]@{Date=$_.TimeCreated.ToString('s');Code=([regex]::Match($_.Message,'0x[0-9A-Fa-f]{8}')).Value;Text=$_.Message.Substring(0,[math]::Min(600,$_.Message.Length))}})
$power=@(Get-Ev 41 'Microsoft-Windows-Kernel-Power' | ForEach-Object {$_.TimeCreated.ToString('s')})
$dirty=@(Get-Ev 6008 'EventLog').Count
$dumpDir=Join-Path $env:SystemRoot 'Minidump';$readable=$true
try{$dumps=@(Get-ChildItem $dumpDir -Filter *.dmp -ErrorAction Stop | Sort-Object LastWriteTime -Descending)}catch{$dumps=@();$readable=-not ($_.Exception -is [System.UnauthorizedAccessException])}
[pscustomobject]@{WindowDays=30;BlueScreens=$bsod;UnexpectedRestarts=$power;DirtyShutdowns=$dirty;MinidumpCount=$dumps.Count;MinidumpReadable=$readable;LatestMinidump=$(if($dumps){$dumps[0].LastWriteTime.ToString('s')}else{$null})}|ConvertTo-Json -Depth 4 -Compress
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
$tcp=@(Get-NetTCPConnection -State Listen | Sort-Object LocalPort,LocalAddress -Unique | Select-Object -First 80 | ForEach-Object { $a=[string]$_.LocalAddress
 [pscustomobject]@{Port=$_.LocalPort;LocalOnly=($a -in '127.0.0.1','::1');Scope=$(if($a -in '127.0.0.1','::1'){'loopback'}elseif($a -in '0.0.0.0','::'){'all'}else{'specific'});Process=$names[[int]$_.OwningProcess]}})
$fw=@(Get-NetFirewallProfile | ForEach-Object {[pscustomobject]@{Profile=[string]$_.Name;Enabled=[bool]$_.Enabled;DefaultInbound=[string]$_.DefaultInboundAction}})
$nets=@(Get-NetConnectionProfile | ForEach-Object {[string]$_.NetworkCategory})
[pscustomobject]@{Tcp=$tcp;UdpCount=@(Get-NetUDPEndpoint).Count;Firewall=$fw;NetworkTypes=$nets}|ConvertTo-Json -Depth 3 -Compress
'''

SECURITY = r'''
# Security posture, all readable without administrator rights. No user names, product keys or recovery keys.
$mp=Get-MpComputerStatus
$av=@(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | ForEach-Object {[pscustomobject]@{Name=[string]$_.displayName;State=[int]$_.productState}})
$fw=@(Get-NetFirewallProfile | ForEach-Object {[pscustomobject]@{Profile=[string]$_.Name;Enabled=[bool]$_.Enabled}})
$pol=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$sb=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State').UEFISecureBootEnabled
$groups=& (Join-Path $env:SystemRoot 'System32\whoami.exe') /groups /fo csv | ConvertFrom-Csv
$admins=$null;try{$admins=@(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction Stop).Count}catch{}
$lic=Get-CimInstance SoftwareLicensingProduct -Filter "ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f' AND PartialProductKey IS NOT NULL" | Select-Object -First 1
$cv=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$hf=Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending | Select-Object -First 1
$bl=$null;try{$bl=(New-Object -ComObject Shell.Application).NameSpace($env:SystemDrive).Self.ExtendedProperty('System.Volume.BitLockerProtection')}catch{}
$tpm=@{};(& (Join-Path $env:SystemRoot 'System32\tpmtool.exe') getdeviceinformation) | ForEach-Object {if($_ -match '^-(TPM Present|TPM Version|Ready For Storage|TPM Has Vulnerable Firmware): *(.*)$'){$tpm[$matches[1]]=$matches[2].Trim()}}
[pscustomobject]@{
 Defender=$(if($mp){[pscustomobject]@{Service=$mp.AMServiceEnabled;Antivirus=$mp.AntivirusEnabled;RealTime=$mp.RealTimeProtectionEnabled;Tamper=$mp.IsTamperProtected;Mode=[string]$mp.AMRunningMode;SignatureAgeDays=$mp.AntivirusSignatureAge;QuickScanAgeDays=$mp.QuickScanAge}}else{$null})
 Antivirus=$av;Firewall=$fw;UacOn=$pol.EnableLUA;UacPrompt=$pol.ConsentPromptBehaviorAdmin;UacSecureDesktop=$pol.PromptOnSecureDesktop;SecureBoot=$sb
 UserIsAdmin=[bool]($groups | Where-Object {$_.SID -eq 'S-1-5-32-544'});LocalAdminCount=$admins;LicenseStatus=$lic.LicenseStatus
 Build=[int]$cv.CurrentBuildNumber;UBR=$cv.UBR;DisplayVersion=[string]$cv.DisplayVersion;Edition=[string]$cv.EditionID
 LastPatch=$(if($hf){[pscustomobject]@{Id=$hf.HotFixID;Date=$hf.InstalledOn.ToString('s')}}else{$null})
 BitLocker=$bl;Tpm=[pscustomobject]$tpm;RemoteDesktopOn=((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server').fDenyTSConnections -eq 0)
 SMB1=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters').SMB1
}|ConvertTo-Json -Depth 4 -Compress
'''

# Event-log signals a technician reads first for freezes and crashes (last 30 days). App names stay on this PC (for_cloud drops them).
SIGNALS = r'''
$since=(Get-Date).AddDays(-30);$week=(Get-Date).AddDays(-7)
function Sig($filter){$e=@(Get-WinEvent -FilterHashtable ($filter+@{StartTime=$since}) -MaxEvents 300)
 [pscustomobject]@{Count=$e.Count;Week=@($e|Where-Object TimeCreated -gt $week).Count;Last=$(if($e){$e[0].TimeCreated.ToString('s')}else{$null});Dates=@($e|Select-Object -First 20|ForEach-Object{$_.TimeCreated.ToString('s')})}}
function Apps($id,$provider){$e=@(Get-WinEvent -FilterHashtable @{LogName='Application';Id=$id;ProviderName=$provider;StartTime=$since} -MaxEvents 300)
 $names=@($e|ForEach-Object{[string]$_.Properties[0].Value})
 [pscustomobject]@{Count=$e.Count;Week=@($e|Where-Object TimeCreated -gt $week).Count;Last=$(if($e){$e[0].TimeCreated.ToString('s')}else{$null});Dates=@($e|Select-Object -First 20|ForEach-Object{$_.TimeCreated.ToString('s')});
  Top=@($names|Group-Object|Sort-Object Count -Descending|Select-Object -First 5|ForEach-Object{[pscustomobject]@{Name=$_.Name;Count=$_.Count}})}}
$out=[pscustomobject]@{WindowDays=30
 GpuResets=Sig @{LogName='System';ProviderName='Display';Id=4101}
 DiskErrors=Sig @{LogName='System';ProviderName='disk';Id=7,51,153}
 StorageResets=Sig @{LogName='System';ProviderName='storahci','stornvme','iaStorAC','iaStorA','iaStorVD','iaStorAVC';Id=129}
 FileSystem=Sig @{LogName='System';ProviderName='Microsoft-Windows-Ntfs';Id=55}
 Hardware=Sig @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger'}
 Thermal=Sig @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Processor-Power';Id=37}
 LowMemory=Sig @{LogName='System';ProviderName='Microsoft-Windows-Resource-Exhaustion-Detector';Id=2004}
 ServiceCrashes=Sig @{LogName='System';ProviderName='Service Control Manager';Id=7031,7034}
 WifiDrops=Sig @{LogName='Microsoft-Windows-WLAN-AutoConfig/Operational';Id=8003}
 AppHangs=Apps 1002 'Application Hang'
 AppCrashes=Apps 1000 'Application Error'}
$out|ConvertTo-Json -Depth 4 -Compress
'''

SCRIPTS = {'security':(SECURITY,45),'event_signals':(SIGNALS,40),'battery':(BATTERY,40),'disk_health':(DISK,30),'crashes':(CRASHES,40),'updates':(UPDATES,40),
           'startup_apps':(STARTUP,25),'pending_reboot':(REBOOT,20),'listening_ports':(PORTS,25)}
TITLES = {'battery':'Battery health','disk_health':'Disk health','crashes':'Crashes and unexpected restarts (last 30 days)',
          'updates':'Windows Update history (last 30 days)','startup_apps':'Startup apps','pending_reboot':'Pending restart',
          'listening_ports':'Network ports listening for connections','security':'Security','event_signals':'Warning signs in the Windows logs (last 30 days)'}
WELL_KNOWN = {7680:'Delivery Optimization (update sharing)',135:'RPC',139:'NetBIOS',445:'File sharing (SMB)',3389:'Remote Desktop',5357:'Network discovery',5040:'Windows service',
              80:'Web server',443:'Web server (HTTPS)',22:'SSH',21:'FTP',3306:'MySQL',1433:'SQL Server',5432:'PostgreSQL',8080:'Web server'}

def check(name):
    if name not in SCRIPTS:raise ValueError('Unknown check')
    script,timeout=SCRIPTS[name]
    data=run(script,timeout)
    if name=='battery' and data.get('available') and data.get('Present'):
        design,full=data.get('DesignCapacity_mWh'),data.get('FullChargeCapacity_mWh')
        data['HealthPercent']=round(100*full/design) if isinstance(design,int) and isinstance(full,int) and design>0 else None
        battery_extras(data)
    if name=='crashes' and data.get('available'):crash_extras(data)
    return data

def iso_minutes(text):
    """'PT1H29M23S' (Windows battery report) -> 89 minutes; None for missing or zero."""
    m=re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?',str(text or ''))
    if not m:return None
    d,h,mi,sec=(float(x or 0) for x in m.groups())
    total=round(d*1440+h*60+mi+sec/60)
    return total or None

def hours_text(minutes):
    h,m=divmod(int(minutes),60)
    return f'{h} h {m:02d} min' if h else f'{m} min'

def battery_extras(data):
    """Runtime at full charge, and the capacity trend from Windows' battery history."""
    data['RuntimeFullMinutes']=iso_minutes(data.pop('RuntimeFull',None))
    data['RuntimeDesignMinutes']=iso_minutes(data.pop('RuntimeDesign',None))
    design=data.get('DesignCapacity_mWh')
    points=[p for p in as_list(data.pop('History',None)) if isinstance(p,dict) and isinstance(p.get('Full_mWh'),int) and p['Full_mWh']>0]
    data['History']=[{'date':p['Date'],'percent':min(100,round(100*p['Full_mWh']/design))} for p in points] if isinstance(design,int) and design>0 else []
    data['Trend']=None
    if len(data['History'])>=2:
        first,last=data['History'][0],data['History'][-1]
        try:days=(datetime.fromisoformat(last['date'])-datetime.fromisoformat(first['date'])).days
        except ValueError:days=0
        if days>=90:
            months=round(days/30.44)
            trend={'since':first['date'],'from':first['percent'],'to':last['percent'],'months':months,'months_to_80':None}
            lost_per_month=(first['percent']-last['percent'])/(days/30.44)
            if lost_per_month>0.05 and last['percent']>80:trend['months_to_80']=round((last['percent']-80)/lost_per_month)
            data['Trend']=trend

def deep_scan():
    """The latest administrator deep scan (deep_scan.py), or None."""
    try:
        with open(DEEP_SCAN_FILE,encoding='utf-8') as f:d=json.load(f)
        return d if isinstance(d,dict) and d.get('finished') else None
    except (TypeError,OSError,ValueError):return None

def crash_extras(data):
    """Stop-code name and meaning for each blue screen, and the likely driver when the deep scan read its dump."""
    deep=deep_scan() or {}
    by_file={x.get('file','').lower():x for x in as_list(deep.get('Dumps')) if isinstance(x,dict)}
    for b in as_list(data.get('BlueScreens')):
        if not isinstance(b,dict):continue
        ev=bluescreen.parse_event(b.pop('Text',''))
        code=ev['code'] if ev else int(b['Code'],16) if re.fullmatch(r'0x[0-9A-Fa-f]+',b.get('Code') or '') else None
        if code is None:continue
        b.update(bluescreen.explain(code));b['Params']=ev['params'] if ev else [];b['Dump']=ev['dump'] if ev else None
        hit=by_file.get((b['Dump'] or '').lower())
        if hit and hit.get('driver'):b['Driver']={k:hit.get(k) for k in ('driver','reason','company','version','driver_date')}
    data['DeepScanDate']=deep.get('finished')

# Windows 11 / 10 Home and Pro end of servicing, as published by Microsoft (Enterprise and Education get longer).
SUPPORT_END = {(11,'21H2'):'2023-10-10',(11,'22H2'):'2024-10-08',(11,'23H2'):'2025-11-11',(11,'24H2'):'2026-10-13',(11,'25H2'):'2027-10-12',(10,'22H2'):'2025-10-14'}
BITLOCKER = {1:'on',2:'off',3:'encrypting',4:'decrypting',5:'suspended',6:'on (locked)'}

def _item(area,state,plain,tech):return {'area':area,'state':state,'plain':plain,'tech':tech}

def security_items(d,today=None):
    """The security posture as rows: {'area','state' (good/note/attention/problem),'plain','tech'}."""
    today=today or date.today();out=[]
    mp=d.get('Defender') or {}
    active=[a for a in as_list(d.get('Antivirus')) if isinstance(a,dict) and (a.get('State',0)>>8)&0xF0==0x10]
    if mp.get('RealTime') and mp.get('Antivirus') and str(mp.get('Mode','Normal')).lower().startswith('normal'):
        age=mp.get('SignatureAgeDays')
        state='good' if age is None or age<=3 else 'attention' if age<=7 else 'problem'
        out.append(_item('Antivirus',state,'Microsoft Defender is on and protecting this PC'+('.' if state=='good' else f', but its virus definitions are {age} days old. Open Windows Security and check for updates.'),
                         f'Defender RTP on · mode {mp.get("Mode")} · signatures {age} d'+(f' · quick scan {mp.get("QuickScanAgeDays")} d' if mp.get('QuickScanAgeDays') is not None and mp.get('QuickScanAgeDays')<10000 else '')))
        if mp.get('Tamper') is False:out.append(_item('Tamper protection','note','Tamper Protection is off, so malware could switch Defender off. Turn it on in Windows Security > Virus & threat protection settings.','Defender IsTamperProtected False'))
    elif active:
        names=', '.join(sorted({a['Name'] for a in active if a.get('Name') and 'defender' not in a['Name'].lower()})) or 'Another antivirus'
        out.append(_item('Antivirus','good',f'{names} is protecting this PC.',f'SecurityCenter2 active: {names}'+(f' · Defender mode {mp.get("Mode")}' if mp else '')))
    else:
        out.append(_item('Antivirus','problem','No antivirus is actively protecting this PC. Open Windows Security and turn on real-time protection.','No active AV in SecurityCenter2; Defender RTP '+str(mp.get('RealTime'))))
    fw=[f for f in as_list(d.get('Firewall')) if isinstance(f,dict)]
    off=[f['Profile'] for f in fw if not f.get('Enabled')]
    if fw:out.append(_item('Firewall','good' if not off else 'problem' if len(off)==len(fw) else 'attention',
                           'Windows Firewall is on.' if not off else f'Windows Firewall is off for {", ".join(off)} networks. Turn it on in Windows Security > Firewall & network protection.',
                           'Firewall '+' · '.join(f'{f["Profile"]} {"on" if f.get("Enabled") else "OFF"}' for f in fw)))
    if d.get('UacOn')==0:out.append(_item('User Account Control','problem','User Account Control is off, so programs can make changes without asking. Turn it back on (search Start for "UAC").','EnableLUA 0'))
    elif d.get('UacPrompt')==0:out.append(_item('User Account Control','attention','User Account Control never asks before changes. Set it back to the default level (search Start for "UAC").','ConsentPromptBehaviorAdmin 0'))
    elif d.get('UacOn') is not None:out.append(_item('User Account Control','good' if d.get('UacSecureDesktop')!=0 else 'note','User Account Control asks before programs make changes.'+('' if d.get('UacSecureDesktop')!=0 else ' Its prompt isn’t on the secure desktop, which is less protected.'),
                                                     f'EnableLUA {d.get("UacOn")} · ConsentPromptBehaviorAdmin {d.get("UacPrompt")} · PromptOnSecureDesktop {d.get("UacSecureDesktop")}'))
    sb=d.get('SecureBoot')
    out.append(_item('Secure Boot','good' if sb==1 else 'attention' if sb==0 else 'note',
                     'Secure Boot is on, which blocks malware that loads before Windows.' if sb==1 else 'Secure Boot is off. Turning it on in the UEFI (BIOS) settings blocks malware that loads before Windows.' if sb==0 else 'Secure Boot status isn’t available (the PC may use legacy BIOS mode).',
                     f'UEFISecureBootEnabled {sb}'))
    tpm=d.get('Tpm') or {}
    if tpm:
        present=str(tpm.get('TPM Present','')).lower()=='true';vuln=str(tpm.get('TPM Has Vulnerable Firmware','')).lower()=='true'
        out.append(_item('TPM','problem' if vuln else 'good' if present else 'attention',
                         'The TPM security chip has vulnerable firmware. Update the TPM firmware from the PC maker.' if vuln else f'The TPM security chip (version {tpm.get("TPM Version")}) is present.' if present else 'No TPM security chip was found. Windows 11 requires TPM 2.0.',
                         f'TPM present {tpm.get("TPM Present")} · version {tpm.get("TPM Version")} · ready for storage {tpm.get("Ready For Storage")} · vulnerable FW {tpm.get("TPM Has Vulnerable Firmware")}'))
    bl=d.get('BitLocker')
    if bl in (1,6):out.append(_item('Drive encryption','good','The Windows drive is encrypted with BitLocker, so a lost or stolen PC doesn’t expose your files.',f'BitLockerProtection {bl} ({BITLOCKER[bl]})'))
    elif bl in (3,4,5):out.append(_item('Drive encryption','attention' if bl==5 else 'note',f'BitLocker is {BITLOCKER[bl]} on the Windows drive.'+(' Protection is paused; resume it in Manage BitLocker.' if bl==5 else ''),f'BitLockerProtection {bl} ({BITLOCKER[bl]})'))
    else:out.append(_item('Drive encryption','note','The Windows drive isn’t encrypted, so anyone with the PC could read its files. On Windows Home, check Settings > Privacy & security > Device encryption; on Pro, turn on BitLocker.',f'BitLockerProtection {bl} (off or unavailable)'))
    if d.get('UserIsAdmin'):out.append(_item('Accounts','note','You sign in with an administrator account. Using a standard account for everyday work stops many attacks from changing the system.',f'Current user in Administrators · local admins {d.get("LocalAdminCount")}'))
    elif d.get('LocalAdminCount') is not None:out.append(_item('Accounts','good','You sign in with a standard account; changes need an administrator’s approval.',f'Current user not in Administrators · local admins {d.get("LocalAdminCount")}'))
    lic=d.get('LicenseStatus')
    if lic is not None:out.append(_item('Activation','good' if lic==1 else 'attention','Windows is activated.' if lic==1 else 'Windows isn’t activated. Check Settings > System > Activation.',f'LicenseStatus {lic}'))
    build,ver=d.get('Build') or 0,d.get('DisplayVersion') or ''
    major=11 if build>=22000 else 10;edition=str(d.get('Edition') or '')
    end=None if re.search(r'Enterprise|Education|IoT|Server',edition) else SUPPORT_END.get((major,ver))
    tech=f'Windows {major} {ver} build {build}.{d.get("UBR")} · {edition}'
    if end:
        left=(date.fromisoformat(end)-today).days
        state='problem' if left<0 else 'attention' if left<=90 else 'good'
        plain=(f'Windows {major} version {ver} stopped getting security updates on {end}. Update to a newer version in Windows Update.' if left<0 else
               f'Windows {major} version {ver} gets security updates until {end} ({left} days). Install the newer version from Windows Update before then.' if left<=90 else
               f'Windows {major} version {ver} gets security updates until {end}.')
        out.append(_item('Windows support',state,plain,tech+f' · end of servicing {end}'))
    else:out.append(_item('Windows support','note',f'Windows {major} version {ver or "unknown"}. PC Medic doesn’t have this version’s support end date; check Microsoft’s Windows lifecycle page.',tech))
    patch=d.get('LastPatch') or {}
    if patch.get('Date'):
        try:days=(today-date.fromisoformat(patch['Date'][:10])).days
        except ValueError:days=None
        if days is not None:out.append(_item('Security updates','good' if days<=45 else 'attention',f'The last Windows update was installed {days} days ago.'+('' if days<=45 else ' Open Windows Update and install what’s waiting.'),f'Last hotfix {patch.get("Id")} {patch["Date"][:10]} ({days} d)'))
    if d.get('RemoteDesktopOn'):out.append(_item('Remote Desktop','note','Remote Desktop is on, so this PC accepts remote sign-ins. Turn it off in Settings > System > Remote Desktop if you don’t use it.','fDenyTSConnections 0'))
    if d.get('SMB1')==1:out.append(_item('SMB1','attention','The old SMB1 file-sharing protocol is on. It has known vulnerabilities; turn it off unless an old device needs it.','LanmanServer SMB1 1'))
    return out

def crash_items(d):
    """Rows for the Blue screens panel."""
    out=[];bsod=[b for b in as_list(d.get('BlueScreens')) if isinstance(b,dict)];restarts=as_list(d.get('UnexpectedRestarts'))
    for b in bsod[:10]:
        drv=b.get('Driver')
        who=(f' Likely cause: {drv["driver"]}'+(f' ({drv["company"]}'+(f', version {drv["version"]}' if drv.get('version') else '')+')' if drv.get('company') else '')+'.') if drv else ''
        out.append(_item(str(b.get('Date',''))[:10],'attention',f'{b.get("name","Blue screen")} ({b.get("code") or b.get("Code")}). {b.get("meaning","")}{who} {"" if drv else b.get("advice","")}'.strip(),
                         f'{b.get("code") or b.get("Code")} {b.get("name","")} · P1-4 {", ".join(b.get("Params") or []) or "?"} · dump {b.get("Dump") or "-"}'+(f' · {drv["driver"]} ({drv.get("reason")})' if drv else '')))
    if restarts:out.append(_item('Restarts','note',f'{len(restarts)} unexpected restart{"s" if len(restarts)!=1 else ""} or power loss{"es" if len(restarts)!=1 else ""} without a blue screen (power loss, a held power button, overheating or a hard freeze).',
                                 f'Kernel-Power 41 ×{len(restarts)} · EventLog 6008 ×{d.get("DirtyShutdowns",0)}'))
    if not bsod and not restarts:out.append(_item('Last 30 days','good','No blue screens or unexpected restarts.','BSOD 0 · Kernel-Power 41 ×0'))
    if bsod and not any(b.get('Driver') for b in bsod):out.append(_item('Driver','note','Run the deep scan below to read the crash dumps and find the likely driver.',f'minidumps {d.get("MinidumpCount")} (readable without admin: {d.get("MinidumpReadable")})'))
    return out

def update_errors(d):
    """Failed updates grouped by error code, most frequent first: [(code, [failures])]."""
    groups={}
    for f in as_list(d.get('Failures')):
        if isinstance(f,dict):groups.setdefault(f.get('Error') or None,[]).append(f)
    return sorted(groups.items(),key=lambda kv:-len(kv[1]))

def update_items(d):
    """Rows for the Windows Update errors panel."""
    out=[]
    for code,group in update_errors(d):
        info=error_codes.lookup(code) if code else None
        names=sorted({f.get('Update') or 'unknown update' for f in group})
        harmless=code=='0x80073D02' or (info and info.get('name')=='WU_E_NOT_APPLICABLE')
        out.append(_item(code or 'Unknown','note' if harmless else 'attention',
                         (f'{len(group)} failed install{"s" if len(group)!=1 else ""}. ' if len(group)>1 else '')+(f'{info["meaning"]} {info["fix"]}' if info else 'No error code was recorded.'),
                         f'{code} {(info or {}).get("name") or ""} ×{len(group)} · last {str(group[0].get("Date"))[:10]} · '+'; '.join(names[:3])+(f' (+{len(names)-3})' if len(names)>3 else '')))
    if not out:out.append(_item('Last 30 days','good',f'No failed updates. {d.get("SuccessCount",0)} installed successfully.',f'WU 30 d: {d.get("SuccessCount",0)} ok · 0 failed'))
    return out

# key: (label, plain description, technical event description)
SIGNALS_TEXT = {
    'GpuResets':('Graphics driver resets','the graphics driver stopped responding and Windows restarted it','Display 4101 (TDR)'),
    'DiskErrors':('Drive errors','the drive reported read problems or retries','disk 7/51/153'),
    'StorageResets':('Drive resets','the drive stopped responding and Windows reset its controller','storport 129'),
    'FileSystem':('File-system damage','Windows found file-system damage on a drive','Ntfs 55'),
    'Hardware':('Hardware errors','the processor, memory or motherboard reported a hardware error','WHEA-Logger'),
    'Thermal':('Processor slowdowns','the processor was slowed down by the firmware, usually because of heat or power limits','Kernel-Processor-Power 37'),
    'LowMemory':('Low memory','Windows ran low on memory','Resource-Exhaustion-Detector 2004'),
    'ServiceCrashes':('Service crashes','Windows services stopped unexpectedly','SCM 7031/7034'),
    'WifiDrops':('Wi-Fi drops','the Wi-Fi connection dropped','WLAN-AutoConfig 8003'),
    'AppHangs':('Programs not responding','programs stopped responding','Application Hang 1002'),
    'AppCrashes':('Program crashes','programs crashed','Application Error 1000'),
}

def signal_items(d):
    """Rows for each warning sign found in the logs."""
    out=[]
    for key,(label,plain,tech) in SIGNALS_TEXT.items():
        sig=d.get(key) or {}
        n=sig.get('Count') or 0
        if not n:continue
        top=[t for t in as_list(sig.get('Top')) if isinstance(t,dict) and t.get('Name')]
        who=f' Mostly {top[0]["Name"]} ({top[0]["Count"]} of {n}).' if top and top[0].get('Count',0)*2>=n and n>=2 else ''
        state='attention' if key in ('DiskErrors','StorageResets','FileSystem','Hardware','GpuResets') or sig.get('Week',0)>=3 else 'note'
        out.append(_item(label,state,f'{n} time{"s" if n!=1 else ""} this month ({sig.get("Week",0)} this week), {plain}. Last: {str(sig.get("Last"))[:10]}.{who}',
                         f'{tech}: {n} in 30 d, {sig.get("Week",0)} in 7 d, last {sig.get("Last")}'+(' · '+', '.join(f'{t["Name"]}×{t["Count"]}' for t in top[:3]) if top else '')))
    if not out:out.append(_item('Event logs','good','No warning signs in the Windows logs this month.','No TDR, disk, storport, NTFS, WHEA, thermal, low-memory, service, Wi-Fi or app hang/crash events in 30 d'))
    return out

SCOPE_RANK={'all':2,'specific':1,'loopback':0}

def port_list(d):
    """One entry per port (IPv4 and IPv6 listeners merged), keeping the widest binding."""
    ports={}
    for t in as_list(d.get('Tcp')):
        if not isinstance(t,dict):continue
        scope=t.get('Scope') or ('loopback' if t.get('LocalOnly') else 'all')
        cur=ports.get(t.get('Port'))
        if not cur or SCOPE_RANK[scope]>SCOPE_RANK[cur['Scope']]:ports[t.get('Port')]={**t,'Scope':scope}
    return sorted(ports.values(),key=lambda t:t.get('Port') or 0)

def port_context(d):
    """What 'listening' does and doesn't mean on this PC."""
    fw=[f for f in as_list(d.get('Firewall')) if isinstance(f,dict)]
    nets=[n for n in as_list(d.get('NetworkTypes')) if n]
    out=[]
    if fw:
        off=[f['Profile'] for f in fw if not f.get('Enabled')]
        blocks=all(str(f.get('DefaultInbound')) in ('Block','NotConfigured') for f in fw)
        out.append(('Windows Firewall is on for all network types' if not off else f'Windows Firewall is OFF for {", ".join(off)}')+
                   (', and blocks incoming connections unless a rule allows them.' if blocks and not off else '.'))
    if nets:out.append(f'Current network type: {", ".join(nets)}.'+(' On Public networks Windows allows fewer incoming connections.' if 'Public' in nets else ''))
    out.append('A listening port is not the same as exposed: other devices can only reach it if the firewall allows it, and the internet can only reach it if the router forwards that port.')
    return out

def items(name,d):
    """Structured rows for checks that have them (the Technician Deep checks screen); [] otherwise."""
    if not d.get('available'):return []
    return security_items(d) if name=='security' else crash_items(d) if name=='crashes' else update_items(d) if name=='updates' else signal_items(d) if name=='event_signals' else []

def month_year(iso):
    try:return datetime.fromisoformat(iso).strftime('%B %Y')
    except ValueError:return iso

def span_text(months):
    """32 -> '2 years and 8 months'."""
    y,m=divmod(int(months),12)
    parts=[f'{y} year{"s" if y!=1 else ""}' if y else '',f'{m} month{"s" if m!=1 else ""}' if m or not y else '']
    return ' and '.join(x for x in parts if x)

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
        if d.get('RuntimeFullMinutes'):
            new=f' (about {hours_text(d["RuntimeDesignMinutes"])} when it was new)' if d.get('RuntimeDesignMinutes') and d['RuntimeDesignMinutes']-d['RuntimeFullMinutes']>=5 else ''
            lines.append(f'On a full charge it lasts about {hours_text(d["RuntimeFullMinutes"])} of active use{new}, going by how this computer has been used lately.')
        t=d.get('Trend')
        if t:
            lines.append(f'Since {month_year(t["since"])} it went from {t["from"]}% to {t["to"]}% of new over {span_text(t["months"])}.'
                         if t['from']!=t['to'] else f'It has held steady since {month_year(t["since"])}.')
            if t.get('months_to_80') and t['months_to_80']<=60:  # beyond five years a straight-line forecast says nothing useful
                lines.append(f'Rough projection: if wear continued at that pace it would reach 80%, where most people notice shorter battery life, in about {span_text(t["months_to_80"])}. '
                             'Battery wear often speeds up with age and heat, so treat this as a guide, not a prediction.')
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
    elif name=='event_signals':
        rows=signal_items(d)
        lines+=[r['plain'] if r['area']=='Event logs' else f'• {r["area"]}: {r["plain"]}' for r in rows]
    elif name=='security':
        items=security_items(d);bad=[i for i in items if i['state'] in ('attention','problem')]
        notes=sum(1 for i in items if i['state']=='note')
        lines.append(('Everything PC Medic checked looks protected.' if not notes else f'The essentials are on. {notes} thing{"s are" if notes!=1 else " is"} worth knowing.') if not bad else f'{len(bad)} thing{"s" if len(bad)!=1 else ""} need{"" if len(bad)!=1 else "s"} attention.')
        lines+=[('✓ ' if i['state']=='good' else '• ')+i['plain'] for i in sorted(items,key=lambda i:i['state']=='good')]
    elif name=='crashes':
        bsod=as_list(d.get('BlueScreens'));restarts=as_list(d.get('UnexpectedRestarts'))
        lines.append(f'Blue screens: {len(bsod)}.'+(' Stop codes: '+', '.join(sorted({b.get("Code") for b in bsod if isinstance(b,dict) and b.get("Code")}))+'.' if bsod else ''))
        seen=set()
        for b in bsod:
            if isinstance(b,dict) and not b.get('name') and re.fullmatch(r'0x[0-9A-Fa-f]+',b.get('Code') or ''):b={**b,**bluescreen.explain(int(b['Code'],16))}
            if not isinstance(b,dict) or not b.get('name') or b['code'] in seen:continue
            seen.add(b['code']);count=sum(1 for x in bsod if isinstance(x,dict) and (x.get('code') or bluescreen.code_hex(int(x.get('Code') or '0',16)))==b['code'])
            lines.append(f'{b["name"]} ({b["code"]}){f", {count} times" if count>1 else ""}: {b["meaning"]}')
            drv=b.get('Driver')
            if drv:lines.append(f'Likely cause: {drv["driver"]}'+(f' from {drv["company"]}' if drv.get('company') else '')+(f', version {drv["version"]}' if drv.get('version') else '')+f' ({drv["reason"]}). Update or roll back that driver first.')
            else:lines.append(b['advice'])
        if bsod and not any(isinstance(b,dict) and b.get('Driver') for b in bsod):
            lines.append('To find the driver behind a blue screen, run the deep scan in Technician mode (Deep checks); it reads the crash dump with administrator permission.')
        lines.append(f'Unexpected restarts or power losses: {len(restarts)}. Improper shutdowns: {d.get("DirtyShutdowns",0)}.')
        if d.get('MinidumpCount'):lines.append(f'Crash dump files saved: {d["MinidumpCount"]} (latest {d.get("LatestMinidump","")[:10]}).')
        if not bsod and not restarts:lines.append('No crashes recorded in the last 30 days.')
        elif not bsod:lines.append('Unexpected restarts without a blue screen often mean power loss, a held power button, overheating or a hard freeze.')
    elif name=='updates':
        lines.append(f'Successful installs: {d.get("SuccessCount",0)}. Failed installs: {d.get("FailureCount",0)}.'+(f' Last success: {str(d.get("LastSuccess"))[:10]}.' if d.get('LastSuccess') else ''))
        for code,group in update_errors(d):
            info=error_codes.lookup(code) if code else None
            names=sorted({re.sub(r'^[0-9A-Z]{12}-','Microsoft Store app ',f.get('Update') or 'unknown update') for f in group})  # Store product IDs mean nothing to people
            lines.append(f'Error {code or "unknown"}{f", {len(group)} times" if len(group)>1 else ""} (last {str(group[0].get("Date"))[:10]}): {names[0]}'+(f' and {len(names)-1} other update{"s" if len(names)>2 else ""}' if len(names)>1 else '')+'.')
            if info:lines.append(f'  What it means: {info["meaning"]} What to do: {info["fix"]}')
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
        tcp=port_list(d);exposed=[t for t in tcp if t['Scope']!='loopback'];dynamic=[t for t in exposed if (t.get('Port') or 0)>=49152]
        lines.append(f'{len(tcp)} TCP ports are listening: {len(exposed)} on a network interface and {len(tcp)-len(exposed)} only for programs on this PC. UDP endpoints: {d.get("UdpCount",0)}.')
        for t in [t for t in exposed if t not in dynamic][:12]:
            label=' · '.join(x for x in (WELL_KNOWN.get(t.get('Port')),t.get('Process'),'all interfaces' if t['Scope']=='all' else 'one network address') if x)
            lines.append(f'Port {t.get("Port")}: {label}')
        if dynamic:lines.append(f'Plus {len(dynamic)} high-numbered ports (49152+), normally Windows services using dynamic ports.')
        lines+=port_context(d)
        lines.append('Physical ports (USB, HDMI) cannot be counted from Windows; check the manufacturer specifications for your model.')
    return TITLES[name]+':\n'+'\n'.join(lines)

def describe_technical(name, d):
    """Compact raw values for Technician mode: the same evidence as describe(), without the plain-English framing."""
    if not d.get('available'):return f'{TITLES[name]}: unavailable ({d.get("reason","")})'
    if name=='battery':
        if not d.get('Present'):return 'Battery: none (desktop or AC-only)'
        mwh=lambda v:f'{v:,}' if isinstance(v,(int,float)) else '?'
        return (f'Battery {d.get("Model") or "?"} · {mwh(d.get("FullChargeCapacity_mWh"))} / {mwh(d.get("DesignCapacity_mWh"))} mWh'
                f' ({d.get("HealthPercent")}%) · {d.get("CycleCount") or "?"} cycles · {"AC" if d.get("OnAC") else "battery"} {d.get("ChargePercent")}%'
                + (f' · runtime {hours_text(d["RuntimeFullMinutes"])} full / {hours_text(d["RuntimeDesignMinutes"]) if d.get("RuntimeDesignMinutes") else "?"} design' if d.get('RuntimeFullMinutes') else '')
                + (f' · {d["Trend"]["from"]}%→{d["Trend"]["to"]}% since {d["Trend"]["since"]}' if d.get('Trend') else ''))
    if name=='disk_health':
        parts=[]
        for x in as_list(d.get('Disks')):
            extra=' · '.join(s for s in (f'{x["TemperatureC"]}°C' if x.get('TemperatureC') else '', f'wear {x["WearPercent"]}%' if x.get('WearPercent') is not None else '',
                                         f'{x["PowerOnHours"]:,} h' if x.get('PowerOnHours') else '') if s)
            errors=(x.get('ReadErrorsUncorrected') or 0)+(x.get('WriteErrorsUncorrected') or 0)
            parts.append(f'{x.get("Name")} · {x.get("MediaType")} {x.get("BusType")} {x.get("SizeGB")} GB · {x.get("Health")}/{x.get("Status")}'
                         + (f' · {extra}' if extra else ' · SMART detail needs admin') + f' · uncorrected errors {errors}')
        parts+=[f'{v.get("Drive")} {v.get("FreeGB")} / {v.get("SizeGB")} GB free' for v in as_list(d.get('Volumes'))]
        return 'Storage: '+' | '.join(parts)
    if name=='event_signals':
        return 'Event signals (30 d): '+' | '.join(r['tech'] for r in signal_items(d))
    if name=='security':
        return 'Security: '+' | '.join(f'{i["area"]} [{i["state"]}] {i["tech"]}' for i in security_items(d))
    if name=='crashes':
        bsod=as_list(d.get('BlueScreens'));codes=sorted({f'{b.get("code") or b.get("Code")} {b.get("name","")}'.strip()+(f' → {b["Driver"]["driver"]}' if b.get('Driver') else '') for b in bsod if isinstance(b,dict) and (b.get('code') or b.get('Code'))})
        return (f'Crashes ({d.get("WindowDays",30)} d): BSOD {len(bsod)}{" " + ",".join(codes) if codes else ""} · Kernel-Power 41 ×{len(as_list(d.get("UnexpectedRestarts")))}'
                f' · EventLog 6008 ×{d.get("DirtyShutdowns",0)} · minidumps {d.get("MinidumpCount",0)}' + (f' (latest {str(d.get("LatestMinidump"))[:10]})' if d.get('LatestMinidump') else ''))
    if name=='updates':
        from collections import Counter
        codes=Counter(f'{f.get("Error") or "?"}'+(f' {(error_codes.lookup(f["Error"]) or {}).get("name") or ""}'.rstrip() if f.get('Error') else '') for f in as_list(d.get('Failures')))
        return (f'Windows Update ({d.get("WindowDays",30)} d): {d.get("SuccessCount",0)} ok · {d.get("FailureCount",0)} failed'
                + (': ' + ', '.join(f'{c} ×{n}' for c,n in codes.most_common()) if codes else '') + (f' · last ok {str(d.get("LastSuccess"))[:10]}' if d.get('LastSuccess') else ''))
    if name=='startup_apps':
        apps=as_list(d.get('Apps'))
        return f'Startup: {len(apps)} entries · ' + ', '.join(re.sub(r'_[0-9A-F]{32}$','',a.get('Name','')) for a in apps)
    if name=='pending_reboot':
        return (f'Reboot pending: CBS {bool(d.get("ComponentServicing"))} · WU {bool(d.get("WindowsUpdate"))} · PendingFileRename {bool(d.get("PendingFileRename"))}'
                f' · last boot {str(d.get("LastBoot"))[:10]} (up {d.get("UptimeDays")} d)')
    if name=='listening_ports':
        tcp=port_list(d);scoped=[t for t in tcp if t['Scope']!='loopback']
        fw=' '.join(f'{f.get("Profile")}:{"on" if f.get("Enabled") else "OFF"}/{f.get("DefaultInbound") or "?"}' for f in as_list(d.get('Firewall')) if isinstance(f,dict))
        return (f'TCP listening {len(tcp)} · bound to a network interface {len(scoped)}: ' + ', '.join(f'{t["Port"]}{"*" if t["Scope"]=="all" else ""}' for t in scoped[:20])
                + f' (* = 0.0.0.0/::) · UDP endpoints {d.get("UdpCount",0)} · firewall {fw or "?"} · network {", ".join(as_list(d.get("NetworkTypes"))) or "?"}')
    return TITLES[name]

def for_cloud(name, d):
    """Data Claude may see: no serials, user names, paths, process names, IPs or MACs."""
    if not d.get('available'):return {'available':False,'reason':d.get('reason')}
    d=json.loads(json.dumps(d))
    if name=='listening_ports':
        d['Tcp']=[{'Port':t.get('Port'),'Scope':t['Scope'],'Service':WELL_KNOWN.get(t.get('Port'))} for t in port_list(d)]  # no process names
    if name=='startup_apps':
        apps=as_list(d.pop('Apps',None))
        d['AllUsers']=sum(a.get('Scope')=='All users' for a in apps);d['ThisUser']=len(apps)-d['AllUsers']
    if name=='battery':d.pop('Model',None)
    if name=='event_signals':
        for k in ('AppHangs','AppCrashes'):
            if isinstance(d.get(k),dict):d[k].pop('Top',None)  # program names stay on this PC
    if name=='security':d.pop('LastPatch',None);d['Items']=[{k:i[k] for k in ('area','state','tech')} for i in security_items(d)]
    if name=='crashes':
        for b in as_list(d.get('BlueScreens')):
            if isinstance(b,dict):b.pop('Dump',None);b.pop('Text',None)
    return d
