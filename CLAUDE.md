# PC Medic AI

A local Windows diagnostic assistant for **laptops and desktops** running Windows 10/11; Windows Server is out of scope. `dashboard.py` is a stdlib HTTP server on 127.0.0.1:8765 that serves the single-page UI `dashboard.html`. Built by Ky with ChatGPT through 1.16.14; Claude Code took over at 1.16.15; see CHANGELOG.md. The version lives in `version.py`.

## Run and test
- Run: `python -u .\dashboard.py` (add `--demo` for simulated data, `--port 8766` for a side-by-side test copy, `--no-window` to skip the Edge app window).
- Install: `pip install -r requirements.txt` (only `anthropic`; everything else is stdlib).
- Tests: `python -m unittest discover -p "test_*.py"`. pytest is not installed.
- JS syntax check: extract the `<script>` block from dashboard.html and run `node --check` on it.
- Ky usually has the real copy running on 8765. Test changes on another port; don't stop Ky's server.

## Architecture rules
- **One routing path:** every Ask PC Medic question goes to `POST /api/intent` → `intent_engine.classify(question, context)`. The browser dispatches on `intent` only. Don't add regex shortcuts in dashboard.html.
- Every request must have Host `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding defense in `Handler.foreign_request`). Every POST needs the `X-PC-Medic-Token` header. The token comes from `GET /api/report` (`csrf`). Hardware and network inventory endpoints are GET only.
- Local collectors are read-only. Windows tools launch only through the `WINDOWS_TOOLS` allowlist with `approved: true`.
- Separate consents: (a) web search terms, (b) cloud LLM evidence, (c) system changes. Use the in-app `pcConfirm()`, not the browser's `confirm()`.
- Parts research uses Claude web search through the `anthropic` SDK (`parts_research.py`). Keep `allowed_callers: ["direct"]`, because dynamic filtering drops citations. Labels are `possible` or `unverified`, never `verified`. With no `ANTHROPIC_API_KEY`, the code must say it did not search; never fall back to scraped results. Live runs cost money (about $0.14 each), so tests mock `_ask_claude`.
- Never send serial numbers, usernames, IPs or the whole scan.json to search or cloud AI. API keys stay in server-side environment variables only.
- Health Check and Performance Watch claim the server's single diagnostic slot (`/api/activity` lease) and pass `owner:windowId` on every sample. New long-running diagnostics must do the same.
- `userSymptom` comes only from the Ask box (`#pc-question`). Never read `#symptom` as user input; it holds PC Medic's output.
- Packaged (.exe) builds (`packaging/build.ps1`; PyInstaller one-folder plus Inno Setup, per-user install): `FROZEN` switches data to `%LOCALAPPDATA%\PC Medic`, and the collector runs as `PCMedic.exe --run-collector`. The .exe is windowed: `sys.stdout` is None, so output goes to `pcmedic.log` (`redirect_output`), and every subprocess must pass `CREATE_NO_WINDOW`. It stops after the last window closes (`/api/window` pings, `idle_exit_due`) and reuses a running copy (`find_running`). Never bundle an API key in a build.
- Claude mode (`assistant.py`): tools must stay read-only and allowlisted in `run_tool`. Anything sent to Claude goes through minimizers (`system_checks.for_cloud`, `computer_overview`). Never add process or app names, serials, user names, paths, IPs or MACs. Keep the conversation history append-only (thinking blocks are replayed unchanged); on failure, roll back the whole turn.
- New read-only checks go in `system_checks.SCRIPTS` with `describe()` and `for_cloud()` handling. Routing goes in the `checks` list in `intent_engine.classify`.
- Windows PowerShell 5 encodes dates in JSON as `/Date(ms)/`; use `event_log_analyzer.event_time()` or emit `.ToString('s')` in the script.
- Every request passes `local_security.same_user()` (the connecting process must run as the same Windows account). Don't add endpoints that bypass `Handler.foreign_request()`.
- Advice that depends on hardware must check `DeviceType` (laptop, desktop, all-in-one, virtual, unknown) and `IdentitySource` (system, motherboard, unknown) from `hardware_advisor.identify()`.
- Guided troubleshooting (`troubleshooter.py`): PC Medic measures and explains; the user makes every change via `action_plan()` steps and the Windows page it opens. New problem types add findings rules, actions and `compare()` handling. Cases live in `cases.json` (local only; names never go to AI).
- AI keys come from `settings.resolve()`: saved (Credential Manager), then environment, then trial (10 uses). Every AI call goes through `settings.key_for_use()` and `settings.record_use()`. Never send key values to the page.
- The trial needs a Google sign-in (`google_auth.py`): `key_for_use` raises `SignInRequired` (a `TrialExhausted`) until `google_auth.account()` exists. Keep scopes at `openid email`, keep only `sub` and `email` (Credential Manager target `PCMedic/google`), and never store or send Google tokens. The callback is a separate one-time listener on 127.0.0.1, not a route on the dashboard server.
- Claude questions are background jobs (`assistant.JOBS`); the page polls `/api/assistant/job`. Keep tools read-only and fast (60 s timeout).
- Output goes in the answer card (`#symptom`), with status in `#assistant-status`. Call `setQuestion()` and `setSource()` (the "Answered by …" label) instead of assigning `currentQuestion`; `archiveTurn()` moves the turn into the history.
- Two modes (`uiMode`: `home` | `tech`, `body.tech`, localStorage `pcmedic-ui-mode`). Hide elements per mode with `data-show="home|tech"`. Anything new that explains evidence needs plain text for Home and raw values for Technician (`describe()` / `describe_technical()`, finding `text` / `tech`, tile `plain` / `tech`).
- Styling uses the Fluent tokens in `<style id="fluent">` (`--accent`, `--surface`, `--good` …), redefined under `body.dark`. Use the tokens; don't add hard-coded colors.
- The Today screen (`today.py`) only runs fast read-only checks (a few seconds total). Anything slower belongs in the Health Check.

## Style
Dense, compact code with one-space indent in dashboard.py and hardware_advisor.py, four spaces elsewhere. Match the file you're in.
