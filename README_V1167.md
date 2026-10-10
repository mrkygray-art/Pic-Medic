# PC Medic V1.16.7 — Hardware Investigation Repair

This test release fixes the hardware inventory browser request. Earlier V1.16.6 incorrectly sent POST to the read-only GET `/api/hardware-upgrade` endpoint, which caused the `Invalid JSON` error. Hardware requests now use GET, validate JSON content type, and report Windows collector failures without claiming to know hardware details.

## Test
1. Extract to a **new** folder; stop older dashboard server with Ctrl+C.
2. Open PowerShell in `pc-medic-ai` and run `python -u .\dashboard.py`.
3. Open `http://127.0.0.1:8765` and refresh (Ctrl+F5).
4. Ask: `What is the model of my computer?` — expect manufacturer/model/BIOS.
5. Ask: `What type of memory do I have installed?` — expect module capacities, speeds and part numbers when exposed by Windows.
6. Ask: `What graphics card do I have?` — expect detected adapter names.
7. Ask: `Can I add more memory?`, then answer `RAM` — expect a hardware inventory rather than Performance Watch.
8. Ask: `My computer froze` — expect Performance Watch; a one-minute watch cannot diagnose a historical freeze by itself.

## Limits
- Windows CIM/WMI data may be missing or incomplete. Report missing values; never invent part numbers or compatibility.
- `Win32_PhysicalMemory` SMBIOS type codes require mapping before asserting DDR generation. The current inventory lists raw available data and module part numbers.
- Upgrade compatibility and current retailer pricing require manufacturer specification verification and live research, not yet implemented.
- No repairs or installations are performed.
