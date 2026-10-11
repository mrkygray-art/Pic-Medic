# PC Medic AI V1.9.2 — Safe Recycle Bin removal

- Fixes PowerShell path parsing using an encoded fixed script and a process-local environment variable.
- Adds a file-specific approval checkbox and Cancel before any move.
- Warns about synced folders and installers.
- Server requires explicit `approved: true`, revalidates location, size and modification time, and moves only to Windows Recycle Bin.
- Existing scans, AI console, and Storage Explorer search are retained.

**Test on Windows:** use a disposable file in Downloads, confirm Cancel leaves it untouched, approve the move, and restore it from Recycle Bin. Do not test on important files.
