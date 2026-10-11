# PC Medic AI V1.10 — Devices & Drivers

New **Devices & Drivers** sidebar page with a local, read-only Windows PnP device inventory, driver provider/version/date, status filtering, and guidance for reviewing device errors. Click **Scan Devices** on demand. No changes to device configuration, drivers, Windows services, or the registry. No device names or driver details are automatically sent to AI providers.

## Start

`python -u dashboard.py` then visit http://127.0.0.1:8765 . On Windows, click **Devices & Drivers → Scan Devices**. PowerShell and Windows PnP/CIM cmdlets must be available. Device inventory may take up to 75 seconds. Some driver information may be unavailable; unknown statuses do not prove device faults.

**Driver uninstall/install/update is intentionally not implemented.** Future driver actions should require explicit, device-specific confirmation, backups/restore point guidance, source verification, and safeguards for critical hardware.
