# PC Medic AI

A Windows technician that lives on your laptop or desktop. Ask it anything about your computer in plain English. It checks the real hardware and Windows settings, explains what it finds, and walks you through fixes. It never changes anything on its own.

Runs on Windows 10 and 11 laptops and desktops. Windows Server is out of scope.

## What it does

- **Answers questions from real data.** It identifies your model, RAM, graphics, storage, battery, network, updates and crashes, so "Can I add more RAM?" is answered with your actual memory slots, not a generic article.
- **Guided troubleshooting.** For "My computer is slow", PC Medic asks when it happens and measures the processor, memory, disk, busiest apps and startup apps. It then explains the evidence, suggests one fix with step-by-step help, measures again, and asks whether it feels better. Each case is saved.
- **Health Check and Performance Watch.** Rule-based scans of storage, drivers, Windows events and performance over time.
- **AI when needed.** In Smart mode (the default), questions the built-in engine can't answer go to Claude, which runs read-only checks and searches the web with cited sources, or to ChatGPT. You approve before anything is shared.
- **Parts research.** Chargers, batteries, RAM and SSDs, researched against your exact model and labeled "possible match" or "unverified", never "guaranteed".
- **Technician report.** A printable summary of the computer, findings, checks, troubleshooting history and the conversation, with space for notes.
- **Tools.** Storage Explorer finds large files and safely moves them to the Recycle Bin. You can also open Windows tools after confirming, and view Devices & Drivers.

## Run from source

1. Install Python 3.10 or newer on Windows, then run `pip install -r requirements.txt` in this folder.
2. Start PC Medic:

   ```powershell
   python -u .\dashboard.py
   ```

3. Open the address it prints (normally `http://127.0.0.1:8765`).

`--demo` uses simulated scan data, and `--port 8766` runs a second copy alongside.

## AI keys

PC Medic works offline without any key. For AI answers, open **Settings** and paste an Anthropic (Claude) or OpenAI (ChatGPT) key. Keys are checked with the provider, then stored in Windows Credential Manager for your Windows account, and are never shown again.

A key set as `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` on the PC also works. Installed copies can include a trial key (`PCMEDIC_TRIAL_ANTHROPIC_API_KEY`) that allows 10 AI questions per Windows account, after which PC Medic asks for the user's own key. Before public release, move the trial key behind a small service. A key bundled inside an app can be extracted.

## Privacy and safety

- The server listens only on this computer, refuses requests from other websites, and answers only the Windows account that started it.
- Every check is read-only. PC Medic opens Windows pages and tools after you confirm; you make every change.
- Nothing leaves the PC in Offline mode. Before Claude or ChatGPT is used, PC Medic asks once per session and lists what is shared. It never sends serial numbers, user or computer names, IP or MAC addresses, file names, or program and process names.
- Storage Explorer only moves files to the Recycle Bin. It refuses files that are too large for the Recycle Bin, because Windows would delete those permanently.

## Updates

PC Medic checks [GitHub Releases](https://github.com/mrkygray-art/Pic-Medic/releases) on startup. When a newer version exists, it shows a direct link to its Windows installer. You can turn this off in Settings, or point it elsewhere with `PCMEDIC_UPDATE_REPO`.

To publish an update, bump `version.py`, then create a GitHub Release tagged `vX.Y.Z` with the installer attached.

## Development

- Tests: `python -m unittest discover -p "test_*.py"`. AI calls are mocked, so the tests cost nothing.
- The version lives in `version.py`, changes are listed in [CHANGELOG.md](CHANGELOG.md), and architecture rules are in [CLAUDE.md](CLAUDE.md).
