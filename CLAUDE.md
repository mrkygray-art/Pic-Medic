# PC Medic AI

A local Windows diagnostic assistant. `dashboard.py` is a stdlib HTTP server on 127.0.0.1:8765 that serves the single-page UI `dashboard.html`. Built by Ky with ChatGPT through 1.16.14; Claude Code took over at 1.16.15 (see README_V11615.md).

## Run and test
- Run: `python -u .\dashboard.py` (add `--demo` for simulated data, `--port 8766` for a side-by-side test copy).
- Install: `pip install -r requirements.txt` (only `anthropic`; everything else is stdlib).
- Tests: `python -m unittest discover -p "test_*.py"`. pytest is not installed.
- JS syntax check: extract the `<script>` block from dashboard.html and run `node --check` on it.
- Ky usually has the real copy running on 8765. Test changes on another port; don't stop Ky's server.

## Architecture rules
- **One routing path:** every Ask PC Medic question goes to `POST /api/intent` → `intent_engine.classify(question, context)`. The browser dispatches on `intent` only. Don't add regex shortcuts in dashboard.html.
- Every POST needs the `X-PC-Medic-Token` header. The token comes from `GET /api/report` (`csrf`). Hardware and network inventory endpoints are GET only.
- Local collectors are read-only. Windows tools launch only through the `WINDOWS_TOOLS` allowlist with `approved: true`.
- Separate consents: (a) web search terms, (b) cloud LLM evidence, (c) system changes. Use the in-app `pcConfirm()`, not the browser's `confirm()`.
- Parts research uses Claude web search through the `anthropic` SDK (`parts_research.py`). Keep `allowed_callers: ["direct"]`, because dynamic filtering drops citations. Labels are `possible` or `unverified`, never `verified`. With no `ANTHROPIC_API_KEY`, the code must say it did not search; never fall back to scraped results. Live runs cost money (about $0.14 each), so tests mock `_ask_claude`.
- Never send serial numbers, usernames, IPs or the whole scan.json to search or cloud AI. API keys stay in server-side environment variables only.
- Keep the existing layout. Output goes in the central assessment box (`#symptom`), with status in `#assistant-status`.

## Style
Dense, compact code with one-space indent in dashboard.py and hardware_advisor.py, four spaces elsewhere. Match the file you're in.
