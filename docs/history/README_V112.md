# PC Medic AI V1.12 — Persistent navigation + Driver Repair Assistant

- Navigation is now a persistent top bar. Only the main workspace scrolls.
- Device cards have a **Driver Repair Assistant** with status-aware, device-specific, read-only guidance.
- Windows Update settings link and copyable `devmgmt.msc` command.
- No automatic driver changes, removals, downloads, or privilege elevation.
- Existing health scan, AI console, Storage Explorer, and safe Recycle Bin features retained.

## Start
`python -u dashboard.py` then visit http://127.0.0.1:8765

## Test
Scan Devices, expand a device, select Driver Repair Assistant. Verify the persistent top navigation while scrolling.
