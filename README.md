# PC Medic AI V1.6 — dual-provider AI diagnostic prototype

Local Windows diagnostics with Claude, OpenAI, and offline provider selection.

## Run

1. Install Python 3.10+ on Windows. Extract this folder.
2. Open PowerShell in the `pc-medic-ai` directory.
3. Configure API keys **in PowerShell** only if you want cloud AI:

   ```powershell
   $env:ANTHROPIC_API_KEY = 'YOUR_CLAUDE_API_KEY'
   $env:OPENAI_API_KEY = 'YOUR_OPENAI_API_KEY'
   ```

   You may configure one or both. Do **not** paste keys into ChatGPT, screenshots, GitHub, or a frontend file. Keys are held by the local Python server, not served to the browser. To use different model IDs, set `PCMEDIC_CLAUDE_MODEL` and `PCMEDIC_OPENAI_MODEL` in your PowerShell environment.
4. Start the local dashboard:

   ```powershell
   python -u .\dashboard.py
   ```

5. Visit `http://127.0.0.1:8765`. Click **Run New Scan**, then open **AI Troubleshooting**. Select Offline, Claude, or OpenAI. Cloud mode requires per-request consent.

For a simulated recruiter demo, run `python -u .\dashboard.py --demo --port 8766` in another window. No real scans are allowed in demo mode. **Cloud AI in demo mode is still a real, billable API request if enabled and approved.**

## Security and limitations

- Binds to 127.0.0.1 only. No login, TLS or public exposure: **do not deploy this local server to Vercel or expose the port**.
- Diagnostic collectors remain read-only. The LLM receives no shell access. Optional `process_memory` is a fixed, allowlisted collector that requires user approval.
- Cloud evidence is a minimized summary, not the entire scan; process names can reveal software. A consent checkbox is required for every cloud request. No diagnostic upload in Offline mode.
- Keys are environment variables, never browser code. The app does not persist cloud conversations; cloud providers may retain API data under their own policies.
- The model can request fixed allowlisted read-only tools; process-memory sampling requires separate explicit user approval. No arbitrary shell execution is possible.
- API requests may incur charges. The default model IDs are configurable and subject to your provider account's availability.
- Offline mode remains available if either API is unavailable. There is no silent fallback that sends data elsewhere.
- The existing process-memory trend is a top-12 working-set comparison, not a memory-leak test.

## Files

- `collector.py`: Windows system collection
- `analyze.py`: deterministic diagnostic findings
- `process_diagnostics.py`: fixed read-only process collector
- `ai_engine.py`: cloud evidence minimization, provider adapters, and allowlisted tool registry
- `dashboard.py`: localhost API, request validation, consent enforcement
- `dashboard.html`: browser interface
- `test_v16.py`: basic security/evidence checks


## V1.14
- Health check first, editable automatic assessment below, Ask PC Medic provider modal at bottom.
- Existing cloud consent and diagnostics retained.
