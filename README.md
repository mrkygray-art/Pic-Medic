# PC Medic AI

A Windows technician that lives on your laptop or desktop. Ask it anything about your computer in plain English. It checks the real hardware and Windows settings, explains what it finds, and walks you through fixes. It never changes anything on its own.

Runs on Windows 10 and 11 laptops and desktops. Windows Server is out of scope.

## What it does

- **Two modes.** *Home* uses plain English, fewer screens and step-by-step help. *Technician* shows raw values, error codes, event IDs and every tool. PC Medic asks on first launch; switch any time at the top of the window.
- **Today screen.** When PC Medic opens, it runs a quick read-only check and gives a one-line verdict plus five tiles: speed, storage, battery (or power on desktops), updates and stability. Click a tile to ask about it.
- **Answers questions from real data.** It identifies your model, RAM, graphics, storage, battery, network, updates and crashes, so "Can I add more RAM?" is answered with your actual memory slots, not a generic article.
- **Guided troubleshooting.** For "My computer is slow", PC Medic asks when it happens and measures the processor, memory, disk, busiest apps and startup apps. It then explains the evidence, suggests one fix with step-by-step help, measures again, and asks whether it feels better. Each case is saved under **Fixes**.
- **Health Check and Performance Watch.** Rule-based scans of storage, drivers, Windows events and performance over time.
- **AI when needed.** In Smart mode (the default), questions the built-in engine can't answer go to Claude, which runs read-only checks and searches the web with cited sources, or to ChatGPT. You approve before anything is shared. Every answer is labeled with who answered it ("Answered by PC Medic · on this PC", "Answered by Claude", ...).
- **Parts research.** Chargers, batteries, RAM and SSDs, researched against your exact model and labeled "possible match" or "unverified", never "guaranteed".
- **Technician report.** A printable summary of the computer, findings, checks, troubleshooting history and the conversation, with space for notes.
- **Tools.** Storage Explorer finds large files and safely moves them to the Recycle Bin. You can also open Windows tools after confirming, and view Devices & Drivers.

## Install

1. Download `PCMedic-Setup-<version>.exe` from [Releases](https://github.com/mrkygray-art/pc-medic/releases/latest).
2. Run it. It installs for your Windows account only, so no administrator approval is needed, and adds PC Medic to the Start menu.
3. The installer isn't code-signed yet, so Windows SmartScreen may say "Windows protected your PC". Click **More info**, then **Run anyway**. You can compare the file's SHA-256 with the one in the release notes (`Get-FileHash .\PCMedic-Setup-*.exe`).

PC Medic opens in its own window. Opening it again brings up the copy that's already running, and it stops by itself about half a minute after you close its last window. Uninstall it from **Settings > Apps**. Your saved checks and troubleshooting history stay in `%LOCALAPPDATA%\PC Medic` until you delete that folder.

## Run from source

1. Install Python 3.10 or newer on Windows, then run `pip install -r requirements.txt` in this folder.
2. Start PC Medic:

   ```powershell
   python -u .\dashboard.py
   ```

PC Medic opens in its own window (Microsoft Edge app mode, without tabs or an address bar). Without Edge it opens in your default browser.

`--demo` uses simulated scan data, `--port 8766` runs a second copy alongside, and `--no-window` starts only the server (open the printed address yourself).

## AI keys

PC Medic works offline without any key. For AI answers, open **Settings** and paste an Anthropic (Claude) or OpenAI (ChatGPT) key. Keys are checked with the provider, then stored in Windows Credential Manager for your Windows account, and are never shown again.

A key set as `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` on the PC also works. Installed copies can include a trial key (`PCMEDIC_TRIAL_ANTHROPIC_API_KEY`) that allows 10 AI questions per Windows account, after which PC Medic asks for the user's own key. Before public release, move the trial key behind a small service. A key bundled inside an app can be extracted.

## Privacy and safety

- The server listens only on this computer, refuses requests from other websites, and answers only the Windows account that started it.
- Every check is read-only. PC Medic opens Windows pages and tools after you confirm; you make every change.
- Nothing leaves the PC in Offline mode. Before Claude or ChatGPT is used, PC Medic asks once per session and lists what is shared. It never sends serial numbers, user or computer names, IP or MAC addresses, file names, or program and process names.
- Storage Explorer only moves files to the Recycle Bin. It refuses files that are too large for the Recycle Bin, because Windows would delete those permanently.

## Build the installer

`powershell -ExecutionPolicy Bypass -File packaging\build.ps1` runs the tests, draws the icon, builds a one-folder app with PyInstaller (`packaging\pcmedic.spec`), and packs it with Inno Setup 6 (`packaging\PCMedic.iss`) into `dist\PCMedic-Setup-<version>.exe`. It needs `pip install pyinstaller pillow` and `winget install JRSoftware.InnoSetup`. The build never includes an API key.

## Updates

PC Medic checks [GitHub Releases](https://github.com/mrkygray-art/pc-medic/releases) on startup. When a newer version exists, it shows a direct link to its Windows installer. You can turn this off in Settings, or point it elsewhere with `PCMEDIC_UPDATE_REPO`.

To publish an update, bump `version.py`, then create a GitHub Release tagged `vX.Y.Z` with the installer attached.

## Development

- Tests: `python -m unittest discover -p "test_*.py"`. AI calls are mocked, so the tests cost nothing.
- The version lives in `version.py`, changes are listed in [CHANGELOG.md](CHANGELOG.md), and architecture rules are in [CLAUDE.md](CLAUDE.md).
