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
$chassis=@((Get-CimInstance Win32_SystemEnclosure).ChassisTypes)
# Battery Name is the OEM battery model (e.g. Lenovo L22D4PA0); DeviceID is omitted because it embeds a serial.
$battery=@(Get-CimInstance Win32_Battery | Select-Object -ExpandProperty Name)
[pscustomobject]@{Manufacturer=$sys.Manufacturer;Model=$sys.Model;PCSystemType=$sys.PCSystemType;ChassisTypes=$chassis;ProductName=$product.Version;BatteryModels=$battery;SystemType=$sys.SystemType;TotalPhysicalMemory=$sys.TotalPhysicalMemory;BoardManufacturer=$board.Manufacturer;BoardProduct=$board.Product;BIOSVersion=$bios.SMBIOSBIOSVersion;Modules=$sticks;Arrays=$arrays;Video=$video;Monitors=$monitors;Drives=$drives} | ConvertTo-Json -Depth 6 -Compress
'''

def clean_product_name(value):
 """Keep a marketing name such as 'LOQ 15IRH8'; drop OEM placeholder strings."""
 text=str(value or '').strip()
 if not text or not re.search(r'[A-Za-z]',text) or re.search(r'to be filled|system version|default string|not applicable|^none$|^n/?a$',text,re.I):return ''
 return text[:60]

# SMBIOS chassis types (Win32_SystemEnclosure) and Win32_ComputerSystem.PCSystemType values.
LAPTOP_CHASSIS={8,9,10,11,12,14,18,21,30,31,32}
DESKTOP_CHASSIS={3,4,5,6,7,15,16,24,35,36}
ALL_IN_ONE_CHASSIS={13}
PLACEHOLDER=re.compile(r'to be filled|system manufacturer|system product name|default string|not applicable|^o\.?e\.?m\.?$|^none$|^n/?a$|^x+\.?x*$|^\s*$',re.I)
VIRTUAL=re.compile(r'virtual|vmware|virtualbox|kvm|qemu|hyper-v|parallels',re.I)

def is_placeholder(value):
 return bool(PLACEHOLDER.search(str(value or '').strip()))

def identify(d):
 """Set DeviceType and, for custom-built PCs with placeholder names, identify the PC by its motherboard."""
 chassis={c for c in (d.get('ChassisTypes') or []) if isinstance(c,int)} if isinstance(d.get('ChassisTypes'),list) else ({d['ChassisTypes']} if isinstance(d.get('ChassisTypes'),int) else set())
 pc_type=d.get('PCSystemType')
 if VIRTUAL.search(' '.join(str(d.get(k) or '') for k in ('Manufacturer','Model'))):kind='virtual'
 elif pc_type==2 or chassis&LAPTOP_CHASSIS:kind='laptop'
 elif chassis&ALL_IN_ONE_CHASSIS:kind='all-in-one'
 elif pc_type in (1,3) or chassis&DESKTOP_CHASSIS:kind='desktop'
 else:kind='laptop' if d.get('BatteryModels') else 'unknown'
 d['DeviceType']=kind
 d['IdentitySource']='system'
 if is_placeholder(d.get('Manufacturer')) or is_placeholder(d.get('Model')):
  board_make,board_model=str(d.get('BoardManufacturer') or '').strip(),str(d.get('BoardProduct') or '').strip()
  d['ReportedManufacturer'],d['ReportedModel']=d.get('Manufacturer'),d.get('Model')
  if board_make and board_model and not is_placeholder(board_make) and not is_placeholder(board_model):
   # Custom-built PCs: the motherboard is the part that decides RAM, storage and CPU compatibility.
   d['Manufacturer'],d['Model'],d['IdentitySource']=board_make,board_model,'motherboard'
  else:
   d['IdentitySource']='unknown'
 return d

def inventory():
 if os.name!='nt': return {'available':False,'reason':'Hardware inventory requires Windows.'}
 try:
  proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',PS],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=18,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if proc.returncode or not proc.stdout.strip(): return {'available':False,'reason':'Windows could not provide hardware inventory.'}
  d=json.loads(proc.stdout.lstrip('\ufeff').strip()); d['available']=True
  d['ProductName']=clean_product_name(d.get('ProductName'))
  identify(d)
  d['RamSummary']=ram_summary(d)
  batteries=d.get('BatteryModels') or []
  d['BatteryModels']=[str(b).strip() for b in (batteries if isinstance(batteries,list) else [batteries]) if str(b).strip()][:2]
  return d
 except (OSError,ValueError,subprocess.TimeoutExpired):return {'available':False,'reason':'Hardware inventory unavailable or timed out.'}


# SMBIOS memory type and form factor codes as reported by Win32_PhysicalMemory.
MEMORY_TYPES={20:'DDR',21:'DDR2',24:'DDR3',26:'DDR4',34:'DDR5',29:'LPDDR3',30:'LPDDR4',35:'LPDDR5'}
FORM_FACTORS={8:'DIMM',12:'SO-DIMM'}

def ram_summary(data):
 """Plain-English reading of the RAM evidence: type, removable or soldered, slots, firmware maximum."""
 mods=data.get('Modules') or [];mods=mods if isinstance(mods,list) else [mods]
 if not mods:return ['Windows did not report individual memory modules, so PC Medic cannot tell whether the RAM is removable. Check the manufacturer specifications.']
 arrays=data.get('Arrays') or [];arrays=arrays if isinstance(arrays,list) else [arrays]
 slots=(arrays[0] if arrays else {}).get('MemoryDevices')
 max_kb=(arrays[0] if arrays else {}).get('MaxCapacityEx') or (arrays[0] if arrays else {}).get('MaxCapacity')
 types=sorted({MEMORY_TYPES.get(m.get('SMBIOSMemoryType')) for m in mods}-{None})
 kind='/'.join(types) or 'unknown type'
 sizes=[round(m['Capacity']/1073741824) for m in mods if isinstance(m.get('Capacity'),(int,float))]
 speed=max([m.get('Speed') or m.get('ConfiguredClockSpeed') or 0 for m in mods])
 lines=[]
 if any(t.startswith('LP') for t in types):
  return [f'Memory type: {kind}. LPDDR memory is always soldered to the motherboard, so it cannot be upgraded or replaced.']
 forms={m.get('FormFactor') for m in mods}
 removable=len(forms)==1 and next(iter(forms)) in FORM_FACTORS
 if removable:
  lines.append(f'Memory type: {kind} {FORM_FACTORS[next(iter(forms))]}. Windows reports {len(mods)} separate removable module(s), so this RAM is not soldered.')
 else:
  lines.append(f'Memory type: {kind}. Windows does not identify all modules as removable (form factor codes {sorted(str(f) for f in forms)}), so some memory may be soldered. Check the manufacturer specifications.')
 if removable and isinstance(slots,int) and slots>0:
  if slots>len(mods):
   lines.append(f'Slots: {slots} reported, {len(mods)} in use, so {slots-len(mods)} may be free. You could add a matching module.')
  elif sizes:
   bigger=max(sizes)*2
   lines.append(f'Slots: {slots} reported and all are in use. To get more RAM you would replace the modules with larger ones, for example {len(mods)} × {bigger} GB = {bigger*len(mods)} GB.')
 if isinstance(max_kb,int) and max_kb>0:
  lines.append(f'Firmware-reported maximum: {max_kb/1048576:g} GB. This is often higher than the manufacturer officially supports, so check the manufacturer specification (for Lenovo, PSREF) before buying more than {sum(sizes)} GB.')
 if removable:
  lines.append(f'Matching modules: {kind} {FORM_FACTORS[next(iter(forms))]}, {speed} MT/s or faster. Replace modules in matched pairs for dual-channel speed.')
 lines.append('Windows reads these details from the laptop firmware, which is usually but not always accurate. The manufacturer specification is the final word.')
 return lines
