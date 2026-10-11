# PC Medic AI V1.15

- Single AI workspace on Overview; removed duplicate AI Console tab and redundant Open AI Console card.
- Run AI-guided Health Check prepares an editable assessment.
- Ask PC Medic opens a provider popup for Offline, Claude, or OpenAI.
- AI answers replace the assessment in the same editable field. Detailed analysis and privacy controls are retained internally.
- Cloud requests still require explicit confirmation and sanitized evidence.
- Offline mode needs no API key. Cloud modes require environment variables in the Python server process.

Run: `python -u dashboard.py`, then refresh the browser.
