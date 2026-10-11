# PC Medic V1.15 — Smarter Diagnosis (Stage 1 test)

Built from the integrated Event Log Analyzer test version. This is a separate test copy, not a replacement for your stable installation.

Changes:
- Provider-aware event triage now prioritizes WHEA hardware events and disk controller errors over benign DCOM noise. Events are clues, not proof of causation.
- Read-only `Get-StorageReliabilityCounter` collection for available physical drives; unsupported counters are not treated as healthy. No automatic drive repair.
- When memory is flagged, the latest top three resident process names and working sets appear in the local finding. Process identities are not sent to cloud AI.
- Symptom text typed before a scan is retained alongside the assessment rather than overwritten. This is context for Ask PC Medic, not yet a symptom-specific diagnostic collector.
- Existing sanitized cloud evidence preview remains available in the Privacy & sharing details section.

Not included yet: continuous spike capture, scheduled scans, crash triggers, disk forecasts, history/trends, KB/error-code extraction, full symptom-specific WLAN/sleep reports, or automatic fix-and-verify. These require separate design and Windows testing.

Run `python -u dashboard.py` from the project directory. Test on Windows; no Windows runtime tests were possible in the build environment.
