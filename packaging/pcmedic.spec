# PyInstaller spec for PC Medic: a windowed, one-folder build (faster to start and fewer antivirus
# false positives than one-file). Build with packaging\build.ps1, which also writes version_info.txt.
from pathlib import Path

ROOT = Path(SPECPATH).parent
HERE = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'dashboard.py')],
    pathex=[str(ROOT)],
    # google_client.json (gitignored) holds the Google sign-in Desktop client; without it, sign-in and the trial stay off.
    datas=[(str(ROOT / 'dashboard.html'), '.')] + ([(str(ROOT / 'google_client.json'), '.')] if (ROOT / 'google_client.json').exists() else []),
    hiddenimports=['collector'],  # imported only in --run-collector mode
    excludes=['tkinter', 'test'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='PCMedic',
    console=False,
    icon=str(HERE / 'pcmedic.ico'),
    version=str(HERE / 'version_info.txt'),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='PCMedic', upx=False)
