# PC Medic V1.16.1 — Watch-only AI analysis fix

- Ask PC Medic can analyze a completed Performance Watch even when no `scan.json` exists. Cloud requests still require explicit consent and are limited to sanitized numeric performance evidence.
- Offline interpretation uses the same watch-only samples and explicitly notes the absence of a full health check.
- When the watch ends, Ask PC Medic and the manual Health Check are highlighted as optional next actions. The emphasis is removed during a diagnostic and honors reduced-motion settings.
- The original reported symptom and watch summary remain visible if AI analysis fails.

Test: Run a one-minute Performance Watch without first running a full Health Check, then choose Ask PC Medic -> Offline. Repeat with Claude/OpenAI only after reviewing cloud-sharing consent. No Windows system changes are performed.
