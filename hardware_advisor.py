"""Read-only local hardware inventory and cautious upgrade guidance."""
import json, os, re, subprocess

PS = r'''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference='SilentlyContinue'
$sys=Get-CimInstance Win32_ComputerSystem
$board=Get-CimInstance Win32_BaseBoard
$bios=Get-CimInstance Win32_BIOS
$sticks=@(Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator,BankLabel,Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType,FormFactor,PartNumber,Manufacturer)
$arrays=@(Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices,MaxCapacity,MaxCapacityEx)
$video=@(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion,VideoProcessor)
$monitors=@(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorID | ForEach-Object { [pscustomobject]@{Manufacturer=([Text.Encoding]::ASCII.GetString([byte[]]($_.ManufacturerName | Where-Object {$_ -gt 0})));Model=([Text.Encoding]::ASCII.GetString([byte[]]($_.UserFriendlyName | Where-Object {$_ -gt 0}))) } })
$drives=@(Get-CimInstance Win32_DiskDrive | Select-Object Model,MediaType,Size,InterfaceType)
$product=Get-CimInstance Win32_ComputerSystemProduct
# Battery Name is the OEM battery model (e.g. Lenovo L22D4PA0); DeviceID is omitted because it embeds a serial.
$battery=@(Get-CimInstance Win32_Battery | Select-Object -ExpandProperty Name)
[pscustomobject]@{Manufacturer=$sys.Manufacturer;Model=$sys.Model;ProductName=$product.Version;BatteryModels=$battery;SystemType=$sys.SystemType;TotalPhysicalMemory=$sys.TotalPhysicalMemory;BoardManufacturer=$board.Manufacturer;BoardProduct=$board.Product;BIOSVersion=$bios.SMBIOSBIOSVersion;Modules=$sticks;Arrays=$arrays;Video=$video;Monitors=$monitors;Drives=$drives} | ConvertTo-Json -Depth 6 -Compress
'''

def clean_product_name(value):
 """Keep a marketing name such as 'LOQ 15IRH8'; drop OEM placeholder strings."""
 text=str(value or '').strip()
 if not text or not re.search(r'[A-Za-z]',text) or re.search(r'to be filled|system version|default string|not applicable|^none$|^n/?a$',text,re.I):return ''
 return text[:60]

def inventory():
 if os.name!='nt': return {'available':False,'reason':'Hardware inventory requires Windows.'}
 try:
  proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',PS],capture_output=True,text=True,timeout=18,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if proc.returncode or not proc.stdout.strip(): return {'available':False,'reason':'Windows could not provide hardware inventory.'}
  d=json.loads(proc.stdout.lstrip('\ufeff').strip()); d['available']=True
  d['ProductName']=clean_product_name(d.get('ProductName'))
  batteries=d.get('BatteryModels') or []
  d['BatteryModels']=[str(b).strip() for b in (batteries if isinstance(batteries,list) else [batteries]) if str(b).strip()][:2]
  return d
 except (OSError,ValueError,subprocess.TimeoutExpired):return {'available':False,'reason':'Hardware inventory unavailable or timed out.'}

def ram_advice(data):
 if not data.get('available'):return 'I cannot inspect this computer yet: '+data.get('reason','Unknown error')+'\nPlease check the manufacturer and exact model in System Information (msinfo32).'
 make=data.get('Manufacturer') or 'Unknown manufacturer'; model=data.get('Model') or 'Unknown model'
 modules=data.get('Modules') or []; modules=modules if isinstance(modules,list) else [modules]
 total=data.get('TotalPhysicalMemory'); gb=round(total/1073741824,1) if isinstance(total,(int,float)) else None
 lines=[f'Computer: {make} {model}.',f'Installed RAM: {gb} GB.' if gb else 'Installed RAM capacity not reported.']
 for m in modules:
  cap=m.get('Capacity'); size=f'{round(cap/1073741824,1)} GB' if isinstance(cap,(int,float)) else 'unknown size'
  lines.append(f"RAM module: {size}, {m.get('Speed') or m.get('ConfiguredClockSpeed') or 'unknown'} MT/s, manufacturer {m.get('Manufacturer') or 'unknown'}, reported part number {str(m.get('PartNumber') or 'unavailable').strip()}, slot {m.get('DeviceLocator') or 'unknown'}.")
 arrays=data.get('Arrays') or [];arrays=arrays if isinstance(arrays,list) else [arrays]
 if arrays:
  slots=arrays[0].get('MemoryDevices');lines.append(f'Windows-reported memory device positions: {slots if slots is not None else "unknown"}. This does NOT confirm free upgradeable sockets.')
 lines.extend(['Upgrade compatibility is NOT confirmed from Windows inventory alone. Some RAM is soldered; BIOS, motherboard, processor and OEM specifications can limit supported capacity and speed.', 'Next: verify the exact model or motherboard on the manufacturer support page. Confirm maximum RAM, socket count, DDR generation, SO-DIMM/DIMM form factor and whether memory is soldered before ordering.', 'I cannot responsibly provide a guaranteed compatible purchase part number or live Amazon/CDW availability without verifying the manufacturer specifications and current listings.'])
 return '\n\n'.join(lines)
