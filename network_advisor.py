"""Read-only local Windows network configuration for offline PC Medic questions."""
import json
import os
import subprocess

PS = r'''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'SilentlyContinue'
$adapters = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | ForEach-Object {
 [pscustomobject]@{
  Description=$_.Description; Index=$_.Index; MACAddress=$_.MACAddress;
  IPAddress=@($_.IPAddress); IPSubnet=@($_.IPSubnet);
  DefaultIPGateway=@($_.DefaultIPGateway); DNSServerSearchOrder=@($_.DNSServerSearchOrder);
  DHCPEnabled=$_.DHCPEnabled; DHCPServer=$_.DHCPServer;
  DHCPLeaseObtained=$_.DHCPLeaseObtained; DHCPLeaseExpires=$_.DHCPLeaseExpires;
  DNSDomain=$_.DNSDomain; DNSHostName=$_.DNSHostName;
  WINSPrimaryServer=$_.WINSPrimaryServer
 }
})
$os=Get-CimInstance Win32_ComputerSystem
[pscustomobject]@{HostName=$env:COMPUTERNAME; Domain=$os.Domain; Adapters=$adapters} | ConvertTo-Json -Depth 6 -Compress
'''

def inventory():
    if os.name != 'nt':
        return {'available': False, 'reason': 'Network inventory requires Windows.'}
    try:
        p = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',PS],
                           capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if p.returncode or not p.stdout.strip():
            return {'available':False,'reason':'Windows network inventory returned no data.'}
        data=json.loads(p.stdout.lstrip('\ufeff').strip())
        if not isinstance(data,dict):raise ValueError('Invalid inventory shape')
        data['available']=True
        return data
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'available':False,'reason':'Windows network inventory unavailable or timed out.'}
