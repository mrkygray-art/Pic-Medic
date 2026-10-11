# Stage 3 preview — disk diagnostics and technician completion status

This test build extends Stage 2.2. Changes:
- Completed health checks show a prominent green banner; interrupted checks show red. Starting a new scan resets the state.
- Read-only **Scan for Disk Health** on Storage and Windows Tools. It queries Windows `Get-PhysicalDisk` and `Get-StorageReliabilityCounter`, where supported, and reports volume free space. It does not run chkdsk /f, optimize, format, or repair.
- C: free-space forecast using scan history. At least three samples spanning 24 hours are required; linear extrapolation is a rough estimate, not a promise. Drive-letter mapping to physical disks is not asserted.

Not yet included: automatic Task Scheduler registration, background notifications, post-crash minidump collection, or automatic cloud AI uploads. These need a separate opt-in implementation and Windows testing.

Test on Windows in a separate extracted folder; preserve your known-good install. Do not store API keys in project files.
