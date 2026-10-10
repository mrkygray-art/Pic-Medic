"""PC Medic AI V1: read-only, local Windows diagnostic collector."""
import argparse
import datetime as dt
import json
import os
import platform
import subprocess
from pathlib import Path


def powershell(script, timeout=20):
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            return {"status": "unavailable", "reason": "command failed or access denied"}
        data = json.loads(result.stdout.strip())
        return {"status": "ok", "data": data}
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError):
        return {"status": "unavailable", "reason": "timed out, unsupported, or invalid output"}


COLLECTORS = {
    "os": "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture,LastBootUpTime | ConvertTo-Json -Compress",
    "cpu": "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,LoadPercentage | ConvertTo-Json -Compress",
    "memory": "$o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{TotalGB=[math]::Round($o.TotalVisibleMemorySize/1MB,2);FreeGB=[math]::Round($o.FreePhysicalMemory/1MB,2)} | ConvertTo-Json -Compress",
    "disks": "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,@{N='SizeGB';E={[math]::Round($_.Size/1GB,2)}},@{N='FreeGB';E={[math]::Round($_.FreeSpace/1GB,2)}} | ConvertTo-Json -Compress",
    "storage_health": "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus | ConvertTo-Json -Compress",
    "drive_reliability": "Get-PhysicalDisk | ForEach-Object { $d=$_; try { $r=$d | Get-StorageReliabilityCounter -ErrorAction Stop; [pscustomobject]@{FriendlyName=$d.FriendlyName;DeviceId=$d.DeviceId;Temperature=$r.Temperature;Wear=$r.Wear;ReadErrorsTotal=$r.ReadErrorsTotal;WriteErrorsTotal=$r.WriteErrorsTotal;ReadErrorsUncorrected=$r.ReadErrorsUncorrected;WriteErrorsUncorrected=$r.WriteErrorsUncorrected} } catch { [pscustomobject]@{FriendlyName=$d.FriendlyName;Unavailable=$true} } } | ConvertTo-Json -Compress -Depth 4",
    "network": "Get-NetAdapter | Select-Object InterfaceDescription,Status,LinkSpeed | ConvertTo-Json -Compress",
}


def collect_event_logs():
    # Read-only; limit channels, time window, and records for predictable scan times.
    # No Security log or raw event Message collected; sensitive messages are excluded.
    script = r"""
$ErrorActionPreference='Stop'
$since=(Get-Date).AddHours(-24)
$channels=@('System','Application','Setup','Microsoft-Windows-WindowsUpdateClient/Operational','Microsoft-Windows-Windows Defender/Operational')
$results=@(foreach($name in $channels){
  try {
    $records=@(Get-WinEvent -FilterHashtable @{LogName=$name;StartTime=$since;Level=@(1,2)} -MaxEvents 80 -ErrorAction Stop | Select-Object Id,ProviderName,Level,TimeCreated)
    [pscustomobject]@{name=$name;status='ok';events=$records}
  } catch {
    if ($_.FullyQualifiedErrorId -like '*NoMatchingEventsFound*') {
      [pscustomobject]@{name=$name;status='ok';events=@()}
    } else { [pscustomobject]@{name=$name;status='unavailable';events=@()} }
  }
})
[pscustomobject]@{window_hours=24;limit_per_channel=80;channels=$results} | ConvertTo-Json -Depth 7 -Compress
"""
    return powershell(script,timeout=45)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="scan.json", help="Local JSON report destination")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This collector runs only on Windows.")
    report = {
        "schema_version": "0.1.0",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "platform": "Windows",
        "read_only": True,
        "checks": {name: powershell(script) for name, script in COLLECTORS.items()},
        "notes": ["No remediation performed", "Unavailable results are not evidence of healthy status", "Storage health status is not a complete SMART assessment"],
    }
    report['checks']['event_log_analysis'] = collect_event_logs()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report saved to {output}")
    print("Check results:")
    for name, result in report["checks"].items():
        print(f"  {name}: {result['status']}")


if __name__ == "__main__":
    main()
