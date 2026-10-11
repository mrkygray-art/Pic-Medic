# PC Medic AI V1.15 — Stage 2 test

New: 30-minute browser-controlled spike watch (10-second sampling; CPU >=90%, RAM >=90%, disk busy >=95%; captures up to 30 top-memory-process snapshots, at most one per minute), local scan history (up to 100 entries), memory trend and previous-scan comparison.

## Important
- Keep the PC Medic tab open for spike watching. No Windows service or scheduled task is installed. Stop Watch stops after the current request/sleep; closing the tab stops collection.
- Spike snapshots are displayed only in the current browser session and are **not persisted**. They show top memory consumers, which may not be the source of a CPU or disk spike.
- `scan_history.json` is stored alongside the program, containing only time, numeric metrics, event window, sample count and finding count; no raw logs, names, or paths. Back it up if you want to retain history.
- No automated fixes, restarts, or background tasks. Stage 1 behavior retained.
- This build has been syntax-checked, but needs real Windows testing.
