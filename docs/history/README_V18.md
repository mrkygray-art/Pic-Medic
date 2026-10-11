# PC Medic AI V1.8 — One-click Health Check

A redesigned, Apple-inspired local Windows diagnostic dashboard built on the existing V1.7 collector and AI backend.

## Start

Open PowerShell in the `pc-medic-ai` directory:

```powershell
python -u .\dashboard.py
```

Open http://127.0.0.1:8765. Stop any previous version first (Ctrl+C).

For simulated demo data (no Windows collector required):

```powershell
python -u .\dashboard.py --demo --port 8766
```

Open http://127.0.0.1:8766.

## Workflow

- **Run Health Check** starts the existing read-only Windows system scan, takes three process-memory snapshots, then captures 13 performance samples approximately 5 seconds apart. No cloud request occurs during this workflow.
- **Findings** are generated locally from the existing rules plus high CPU / high memory / very low available RAM observations. They are not proof of root cause.
- **AI Console** (on Overview and in its own tab) automatically includes the latest system scan and available sanitized performance samples. Choose Offline, Claude or OpenAI; type a question or select findings; press **Investigate**. Cloud providers require confirmation for every request.
- **Performance / Storage / Findings / System Details** are views of already collected data, not additional tests.
- **Stop** stops the sequential investigation after its current measurement. **Export** creates a local JSON report that may contain process names and PIDs; review before sharing.
- Light/dark theme toggle in the top-right corner.

## API keys

Only needed for cloud providers. Set in the same PowerShell session used to launch PC Medic:

```powershell
$env:ANTHROPIC_API_KEY = 'your-key'
$env:OPENAI_API_KEY = 'your-key'
python -u .\dashboard.py
```

Keys are read by the local Python server and are not embedded in the browser page. Do not paste real keys into chat, screenshots, or GitHub.

## Important limitations

- Prototype for local use, not production endpoint management.
- Windows scanning must be tested on your machine. Existing unit tests and JavaScript syntax checks pass; browser end-to-end testing could not be completed in the build environment.
- A 60-second sample cannot diagnose a memory leak or establish root cause. Disk counters can be missing or misleading.
- The AI API request includes your question verbatim and sanitized diagnostic evidence. Review the confirmation carefully.
- An optional cloud diagnostic tool is disabled by default in this interface. No repairs or destructive actions are performed.
- Previous V1.7.x diagnostic history held in browser memory is not migrated across versions. Export important results first.
