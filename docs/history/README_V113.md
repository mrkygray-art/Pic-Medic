# PC Medic AI V1.13 — AI-first overview and left navigation

- Fixed upper-left sidebar, independently scrolling workspace.
- AI-led Overview with optional symptom intake, one-click local health check and verdict.
- CPU average and peak across performance samples.
- Explicitly unavailable SMART/SSD wear/temperature/fan telemetry instead of guessed health values.
- Windows Optimize Drives launch from Storage (does NOT start optimization). Windows chooses TRIM for SSDs and defrag for HDDs; user remains in control.
- Existing AI console, storage explorer, driver diagnostics, consent and local scan preserved.

## Run
`python -u dashboard.py` then open http://127.0.0.1:8765.

## Limitations
Verdict is rule-based and preliminary. No automatic cloud calls, no automatic repair, no raw SMART telemetry, no PDF/history in this release.
