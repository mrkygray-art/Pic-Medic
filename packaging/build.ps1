# Build the PC Medic installer: tests, icon, PyInstaller one-folder app, then the Inno Setup installer.
# Output: dist\PCMedic-Setup-<version>.exe
# Needs: Python with requirements.txt + pyinstaller + pillow, and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# The build never contains an API key: keys come from Settings (Credential Manager) or the environment at run time.
# Windows PowerShell 5 treats anything a program writes to stderr as an error, so check exit codes instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$version = (Select-String -Path version.py -Pattern 'VERSION = "([0-9.]+)"').Matches[0].Groups[1].Value
Write-Host "PC Medic $version"

python -m unittest discover -p "test_*.py"
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; not building.' }

python packaging\make_icon.py packaging\pcmedic.ico
if ($LASTEXITCODE -ne 0) { throw 'Icon failed.' }

$parts = ($version.Split('.') + @('0', '0', '0'))[0..3] -join ', '
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Ky Gray'),
      StringStruct('FileDescription', 'PC Medic'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'PCMedic'),
      StringStruct('OriginalFilename', 'PCMedic.exe'),
      StringStruct('ProductName', 'PC Medic'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 packaging\version_info.txt

python -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work packaging\pcmedic.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup' }
& $iscc /Q "/DAppVersion=$version" packaging\PCMedic.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }

$setup = Get-Item "dist\PCMedic-Setup-$version.exe"
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash
Write-Host "Built $($setup.FullName) ($([math]::Round($setup.Length / 1MB, 1)) MB)"
Write-Host "SHA-256 $hash"

