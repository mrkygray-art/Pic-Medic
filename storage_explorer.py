"""Opt-in, bounded, local-only file inventory and safe Recycle Bin operations."""
import os
import re
import secrets
import time
from pathlib import Path

MAX_FILES = 120000
MAX_SECONDS = 40
MAX_RESULTS = 250
CACHE_TTL = 1800
TOKENS = {}  # window id -> {token: (path, expires, size, mtime_ns)}; each window keeps its own selections
CATEGORIES = {
 'images': {'.jpg','.jpeg','.png','.gif','.webp','.bmp','.tif','.tiff','.heic','.raw','.cr2','.nef'},
 'videos': {'.mp4','.mov','.avi','.mkv','.wmv','.webm','.m4v'},
 'documents': {'.pdf','.txt','.json','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.csv','.md','.rtf'},
 'email': {'.pst','.ost','.eml','.msg','.mbox'},
 'archives': {'.zip','.7z','.rar','.tar','.gz','.iso'},
 'installers': {'.exe','.msi','.msix','.cab'},
}

def category(path):
 suffix=path.suffix.lower()
 return next((name for name,extensions in CATEGORIES.items() if suffix in extensions),'other')

def roots():
 home=Path.home()
 # Include redirected Known Folders (OneDrive/other sync providers) as well as normal folders.
 found=[]
 for base in (home,home/'OneDrive',*home.glob('OneDrive - *')):
  for name in ('Downloads','Desktop','Documents','Pictures','Videos','Music'):
   path=base/name
   try:
    if path.is_dir() and not path.is_symlink() and path.resolve() not in [x.resolve() for x in found]:found.append(path)
   except OSError:pass
 return found

def search_roots(scope):
 home=Path.home()
 if scope=='personal':return roots()
 if scope=='profile':return [home]
 if scope=='drives':
  from string import ascii_uppercase
  return [Path(f'{letter}:/') for letter in ascii_uppercase if Path(f'{letter}:/').is_dir()]
 raise ValueError('Invalid search scope')

BLOCKED_NAMES={'windows','program files','program files (x86)','programdata','appdata','$recycle.bin','system volume information','recovery','windowsapps','msocache','perflogs'}
def excluded(path):
 return any(part.lower() in BLOCKED_NAMES for part in Path(path).parts)

REPARSE_POINT=0x400

def is_link(path):
 """Symlink or junction. Path.stat() follows junctions, so read the attribute with lstat()."""
 return os.path.islink(path) or bool(getattr(os.lstat(path),'st_file_attributes',0)&REPARSE_POINT)

def allowed(path):
 try:
  p=Path(path)
  if p.is_symlink() or not p.is_file(): return False
  real=p.resolve(strict=True)
  if not any(real.is_relative_to(r.resolve(strict=True)) for r in roots()): return False
  # Exclude nested junctions/reparse points and known sensitive/application directories.
  for ancestor in (p,*p.parents):
   if ancestor.parent==ancestor:break  # drive root
   if is_link(ancestor):return False
  return True
 except (OSError,ValueError):return False

def inventory(minimum_mb=100,kind='all',scope='profile',owner='default'):
 if os.name!='nt':raise RuntimeError('Local Windows scanning is required')
 if kind not in ('all',*CATEGORIES):raise ValueError('Unsupported file category')
 if scope not in ('personal','profile','drives'):raise ValueError('Unsupported scan scope')
 if not isinstance(minimum_mb,(int,float)) or not 1<=minimum_mb<=102400:raise ValueError('Minimum size must be between 1 and 102400 MB')
 start=time.monotonic();count=0;matched=[];inaccessible=0;timed_out=False
 selected_roots=search_roots(scope)
 for root in selected_roots:
  if excluded(root):continue
  for folder,dirs,files in os.walk(root,followlinks=False):
   if time.monotonic()-start>MAX_SECONDS or count>=MAX_FILES:timed_out=True;break
   kept=[]
   for d in dirs:
    p=Path(folder)/d
    try:
     if excluded(p) or is_link(p):continue
     kept.append(d)
    except OSError:inaccessible+=1
   dirs[:]=kept
   for name in files:
    count+=1
    if count>MAX_FILES or time.monotonic()-start>MAX_SECONDS:timed_out=True;break
    p=Path(folder)/name
    try:
     if excluded(p) or is_link(p):continue
     stat=p.stat()
     if stat.st_size<minimum_mb*1048576:continue
     c=category(p)
     if kind!='all' and c!=kind:continue
     can_recycle=allowed(p)
     matched.append((stat.st_size,p,c,can_recycle,stat.st_mtime_ns))
    except (OSError,ValueError):inaccessible+=1
   if timed_out:break
  if timed_out:break
 matched.sort(key=lambda x:x[0],reverse=True)
 # The same file can be reachable twice (e.g. OneDrive and a redirected folder); list it once.
 seen=set();unique=[]
 for item in matched:
  try:key=os.path.normcase(str(item[1].resolve()))
  except OSError:key=os.path.normcase(str(item[1]))
  if key not in seen:seen.add(key);unique.append(item)
 tokens=TOKENS[str(owner)[:64]]={};results=[]
 if len(TOKENS)>20:TOKENS.pop(next(iter(TOKENS)))
 for size,p,c,can_recycle,mtime_ns in unique[:MAX_RESULTS]:
  token=secrets.token_urlsafe(24) if can_recycle else None
  if token:tokens[token]=(str(p),time.monotonic()+CACHE_TTL,size,mtime_ns)
  results.append({'id':token,'name':p.name,'folder':str(p.parent),'size_mb':round(size/1048576,1),'category':c,'classification':'Personal file — review before recycling' if can_recycle else 'Review only — deletion disabled outside approved personal folders','recyclable':can_recycle})
 return {'files':results,'scanned_files':count,'matches':len(unique),'limited':timed_out or len(unique)>MAX_RESULTS,'inaccessible':inaccessible,'folders':[str(x) for x in selected_roots],'note':'Scanned selected scope excluding Windows, Program Files, AppData, ProgramData and protected directories. Deletion is available only in approved personal folders. Mailbox attachments inside email databases are not inspected.'}

BITBUCKET=r'Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume'

def recycle_bin_limit(path):
 """Recycle Bin settings for the drive holding `path`: {'disabled': bool, 'max_bytes': int|None}, or None if unknown."""
 import ctypes,winreg
 k32=ctypes.WinDLL('kernel32',use_last_error=True)
 root=ctypes.create_unicode_buffer(300);volume=ctypes.create_unicode_buffer(100)
 if not k32.GetVolumePathNameW(str(path),root,300) or not k32.GetVolumeNameForVolumeMountPointW(root.value,volume,100):return None
 guid=re.search(r'\{[0-9A-Fa-f-]{36}\}',volume.value)
 if not guid:return None
 try:
  with winreg.OpenKey(winreg.HKEY_CURRENT_USER,BITBUCKET+'\\'+guid.group(0)) as key:
   def value(name):
    try:return int(winreg.QueryValueEx(key,name)[0])
    except (OSError,ValueError):return None
   nuke,max_mb=value('NukeOnDelete'),value('MaxCapacity')
 except OSError:return None
 return {'disabled':nuke==1,'max_bytes':max_mb*1048576 if max_mb else None}

def recycle_refusal(path,size):
 """Why Windows would permanently delete this file instead of recycling it, or None."""
 limit=recycle_bin_limit(path)
 if not limit:return None
 if limit['disabled']:return 'The Recycle Bin is turned off for this drive, so Windows would delete the file permanently. PC Medic did not delete it.'
 if limit['max_bytes'] and size>limit['max_bytes']:
  readable=lambda b:f'{b/1073741824:.1f} GB' if b>=1073741824 else f'{b/1048576:.0f} MB'
  return f'This file ({readable(size)}) is larger than the Recycle Bin on this drive ({readable(limit["max_bytes"])}), so Windows would delete it permanently. PC Medic did not delete it. Copy it elsewhere first, or delete it yourself in File Explorer if you are sure.'
 return None

SHELL_ERRORS={2:'The file no longer exists.',5:'Windows denied access to the file.',32:'The file is open in another program. Close it and try again.',
              0x78:'Windows denied access to the file.',0x7C:'The file path is not valid.',0x10000:'Windows could not move the file.'}

def send_to_recycle_bin(path):
 """Recycle one file with the shell. FOF_WANTNUKEWARNING makes Windows ask before any permanent delete."""
 import ctypes
 from ctypes import wintypes
 class SHFILEOPSTRUCTW(ctypes.Structure):
  _fields_=[('hwnd',wintypes.HWND),('wFunc',wintypes.UINT),('pFrom',wintypes.LPCWSTR),('pTo',wintypes.LPCWSTR),('fFlags',ctypes.c_ushort),
            ('fAnyOperationsAborted',wintypes.BOOL),('hNameMappings',ctypes.c_void_p),('lpszProgressTitle',wintypes.LPCWSTR)]
 FO_DELETE=3;FOF_SILENT=0x4;FOF_NOCONFIRMATION=0x10;FOF_ALLOWUNDO=0x40;FOF_NOERRORUI=0x400;FOF_WANTNUKEWARNING=0x4000
 op=SHFILEOPSTRUCTW(None,FO_DELETE,str(path)+'\0',None,FOF_ALLOWUNDO|FOF_WANTNUKEWARNING|FOF_NOCONFIRMATION|FOF_SILENT|FOF_NOERRORUI,False,None,None)
 code=ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
 if op.fAnyOperationsAborted:raise RuntimeError('Cancelled. The file was not deleted.')
 if code:raise RuntimeError('Could not move the file to the Recycle Bin: '+SHELL_ERRORS.get(code,f'Windows error {code}.'))

def recycle(token,owner='default'):
 if os.name!='nt':raise RuntimeError('Recycle Bin is available only on Windows')
 tokens=TOKENS.get(str(owner)[:64],{})
 entry=tokens.get(token)
 if not entry:raise ValueError('File selection expired. Scan again.')
 path,expires,size,mtime_ns=entry
 if time.monotonic()>expires:raise ValueError('File selection expired. Scan again.')
 p=Path(path)
 try:current=p.stat()
 except OSError:raise ValueError('File changed or is no longer eligible. Scan again.')
 if not allowed(p) or current.st_size!=size or current.st_mtime_ns!=mtime_ns:raise ValueError('File changed or is no longer eligible. Scan again.')
 refusal=recycle_refusal(p,size)
 if refusal:raise RuntimeError(refusal)
 send_to_recycle_bin(p)
 if p.exists():raise RuntimeError('Could not move the file to the Recycle Bin. It is still in place.')
 tokens.pop(token,None)
 return {'recycled':True,'message':'Moved to Windows Recycle Bin. Restore it there if needed.'}
