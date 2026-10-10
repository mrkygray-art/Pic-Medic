"""Read-only Windows PnP device inventory. No driver or device modifications."""
import json
import os
import subprocess

SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$devices = @(Get-PnpDevice | Select-Object -Property FriendlyName,Class,Status,InstanceId,Problem)
$drivers = @{}
Get-CimInstance Win32_PnPSignedDriver | ForEach-Object {
  if ($_.DeviceID) {
    $drivers[$_.DeviceID] = @{ Provider = $_.DriverProviderName; Version = $_.DriverVersion; Date = if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { $null } }
  }
}
$result = foreach ($d in $devices) {
  $driver = $drivers[$d.InstanceId]
  [PSCustomObject]@{ name = [string]$d.FriendlyName; category = [string]$d.Class; status = [string]$d.Status; problem_code = if ($null -ne $d.Problem) { [string]$d.Problem } else { '' }; driver_provider = if ($driver) { [string]$driver.Provider } else { '' }; driver_version = if ($driver) { [string]$driver.Version } else { '' }; driver_date = if ($driver) { [string]$driver.Date } else { '' } }
}
ConvertTo-Json -InputObject @($result) -Depth 4 -Compress
"""

def inventory(demo=False):
    if demo:
        return {'devices': [{'name':'Demo Wi-Fi Adapter','category':'Net','status':'OK','problem_code':'','driver_provider':'Demo','driver_version':'1.0','driver_date':'2026-01-01'}, {'name':'Demo USB Device','category':'USB','status':'Error','problem_code':'28','driver_provider':'','driver_version':'','driver_date':''}], 'demo': True}
    if os.name != 'nt':
        raise RuntimeError('Device inventory is supported on Windows only')
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',SCRIPT],capture_output=True,text=True,timeout=75,check=False)
    if result.returncode:
        raise RuntimeError('Windows device inventory failed: '+result.stderr[-350:])
    try:
        devices=json.loads(result.stdout.strip().lstrip('\ufeff'))
    except (ValueError,TypeError) as exc:
        raise RuntimeError('Windows returned invalid device data') from exc
    if not isinstance(devices,list):
        raise RuntimeError('Unexpected device inventory response')
    safe=[]
    for d in devices[:2000]:
        if not isinstance(d,dict):continue
        safe.append({key:str(d.get(key) or '')[:200] for key in ('name','category','status','problem_code','driver_provider','driver_version','driver_date')})
    return {'devices':safe,'demo':False,'total':len(safe),'attention':sum(1 for d in safe if d['status'].lower() not in ('ok','unknown'))}
