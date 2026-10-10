# PC Medic AI V1.9 — Storage Explorer

New sidebar tab: **Storage Explorer**. On-demand, local-only search of Downloads, Desktop, Documents, Pictures, Videos and Music. No whole-drive traversal; Windows/system folders and app data are excluded. Supports category filters and minimum size, top 250 matches, bounded scan (40 seconds/120,000 files). Search does not upload file paths or content to AI.

**Recycle Bin:** Each result has a one-click **Move to Recycle Bin** action. It is not permanent deletion. The backend verifies an opaque per-scan file token, folder allowlist, no symlinks/junctions and unchanged file size. Restore from Windows Recycle Bin if needed. No automatic cleanup. **Back up important files before removing anything.**

**Email limitation:** Lists locally stored PST/OST/EML/MSG/mbox files; does not read mailbox content or find individual cloud email attachments.

Run on Windows: `python -u .\dashboard.py`; visit http://127.0.0.1:8765. Cloud API keys remain optional.

Windows integration requires live validation; Linux tests cannot verify Windows Recycle Bin behavior.
