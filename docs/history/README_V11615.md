# PC Medic AI 1.16.15: conversation and research fixes

## Root causes found in 1.16.14
- **Research returned useless results that looked like real ones.** Without a Brave key, `parts_research.py` used Bing's public RSS feed. The feed ignores the query and always returns the Lenovo homepage, Lenovo Support and Wikipedia. The UI then reported "Search complete · 8 candidate sources".
- **"Yes, research it" lost context.** The browser's yes-reply regex did not allow a comma.
- **Stale "Search online for parts" buttons** stayed visible during unrelated questions and researched the old part when clicked.
- **"What is my IP?" printed the IPv4 address twice.**
- **Two routing paths that disagreed.** About 10 regex shortcuts in `dashboard.html` ran before `intent_engine.py`. For example, the server classified "I need a new charger" as battery-health advice.

## Changes
- `intent_engine.classify(question, context)` is now the single routing path. It adds the intents `replacement_part` (with `part`), `open_tool` (with `tool`), `ports_clarify`, `research_confirm` and `research_decline`. Upgrade questions return `ram_upgrade`, `storage_upgrade` or `graphics_upgrade`. The browser sends `context.pending_research`, so short replies are interpreted against the open offer.
- `parts_research.py` was rewritten to use **Claude's server-side web search**:
  - It uses the official `anthropic` SDK (`pip install -r requirements.txt`) and needs `ANTHROPIC_API_KEY`. The model is `claude-opus-5-5`; override it with `PCMEDIC_RESEARCH_MODEL`. Anthropic's server-side fallback is on (`fallbacks: "default"`), so a declined request is retried on another model.
  - It uses `web_search_20260318` with direct calls (`allowed_callers: ["direct"]`). Dynamic filtering returned answers with no citations. The tool is capped at 5 searches and limited to the manufacturer's domain plus major retailers.
  - Claude's answer is shown with numbered citations. Each cited source is labeled **Possible match** (mentions the exact model, a model token such as "15IRH8", or the part number) or **Unverified**. Nothing is ever labeled verified.
  - Without a key, or if the API fails, it says plainly that it did not search and returns direct manufacturer and retailer links.
  - Cost: $10 per 1,000 searches plus tokens. A live charger run used 2 searches and about 25k input / 800 output tokens, roughly $0.14.
- New endpoint `POST /api/parts-research-preview` returns the exact prompt, allowed domains and shared fields. The consent dialog shows them before anything is sent.
- `hardware_advisor.inventory()` now also reports `ProductName` (for example "LOQ 15IRH8", from `Win32_ComputerSystemProduct.Version`) and `BatteryModels` (the OEM battery part number, for example "L22D4PA0"). The battery DeviceID is excluded because it contains a serial number.
- The UI clears stale offers when a new topic starts, disables research buttons while research runs, scrolls the results into view, and corrects the version label.

## Follow-up bug fixes
- **DNS rebinding (security).** Any website could resolve its own name to 127.0.0.1, read the request token from `/api/report` and send commands: open tools, read the registry, recycle files, run paid research. Every request must now use Host `127.0.0.1:<port>` or `localhost:<port>`, and any Origin must match.
- **The assessment text was treated as the user's symptom.** Missing braces in `healthCheck()`, plus the same pattern in `updateAssessment()`, copied PC Medic's previous answer (for example charger research) into the Health Check as "Your reported symptom". `userSymptom` now comes only from the Ask box, and a manual Health Check starts with none.
- **The scan would break in a packaged .exe.** It relaunched `sys.executable collector.py`. A frozen build now relaunches itself with `--run-collector`. Scan data and history go to `%LOCALAPPDATA%\PC Medic` when frozen.
- **Diagnostics could overlap across windows.** A server-side lease (`POST /api/activity`, renewed by each sample, expiring after 90 seconds) now allows one Health Check or Performance Watch at a time across all windows. The other window shows an amber "blocked" message.

## New features
- **Chat history.** Earlier questions and answers stack as chat bubbles above the current answer. The answer box is read-only output.
- **Seven read-only checks** (`system_checks.py`, `GET /api/check?name=`): battery wear (`powercfg /batteryreport`), disk health and free space, blue screens and unexpected restarts (30 days), Windows Update failures (30 days), startup apps, pending restart, and listening network ports. Questions route to them through the `system_check` intent. `for_cloud()` removes process names, app names and duplicates before Claude sees anything.
- **Claude investigation mode** (`assistant.py`, `POST /api/assistant`). An "Answer with: Offline | Claude" switch, with Offline as the default. Claude (`claude-opus-5-5`, override with `PCMEDIC_ASSISTANT_MODEL`) chooses among read-only tools: computer overview, a system check, recent errors, performance snapshot, network status and web search. Conversations are held on the server, so follow-ups keep context. Consent is asked once per page session. Offline fallbacks (howto, clarify) offer "Ask Claude instead". A live test cost about $0.10–0.25 per question.
- **Technician report** (`report.py`, `POST /api/technician-report`). One printable HTML page with computer details, Health Check findings, current checks, recent errors, the session's questions and answers, and editable technician notes. Print / Save as PDF. All text is HTML-escaped.

## Laptops, desktops and shared computers
- **Computer type.** `hardware_advisor.identify()` reads the chassis type and `PCSystemType` and sets `DeviceType`: laptop, desktop, all-in-one, virtual or unknown. On desktops, charger questions get power-supply guidance and research, battery questions explain the CR2032 coin cell, and graphics and storage advice covers PCIe cards and drive bays. Claude and the technician report also see the type.
- **Custom-built PCs.** When the manufacturer or model is a placeholder ("To Be Filled By O.E.M.", "System Product Name"), the motherboard becomes the identity (`IdentitySource: motherboard`). Parts research accepts maker names with commas and knows the Gigabyte, ASRock and Biostar sites.
- **One Windows account only** (`local_security.py`). Each request's connection is matched to its process through Windows' TCP table, and that process's account must match the server's. Anything unverifiable is refused. The server binds its port exclusively, so no other account can bind on top of it, and moves to the next free port if 8765 is taken.

## Answering any question
- **Answer modes:** Offline only, **Smart** (the default) and Claude. In Smart mode the built-in engine answers when it can. Questions it does not recognize (`clarify` and `howto` intents) go to Claude, or to ChatGPT if only an OpenAI key exists, after a one-time consent. With no AI service, a problem description starts the AI-guided Health Check. Otherwise PC Medic shows Ask Claude, Ask ChatGPT, Run Health Check and Run Performance Watch buttons.
- **Gaming:** "Can this run games?" is answered offline from the strongest real graphics adapter (virtual display drivers are ignored), plus RAM and laptop power advice.
- **API keys:** the server reads `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from the user's saved environment (`HKCU\Environment`) when the launching window predates `setx`.
- **Startup:** the answer box starts empty. The last Health Check summary appears only after a Health Check runs.
- **Known limitation:** the ChatGPT path reuses the original `ai_engine` analysis prompt. It cannot run checks or search the web, and it frames answers around the latest Health Check, so Claude gives much better general answers.

## Review fixes (four parallel reviews of the inherited features)
- **Serious:**
  - Storage Explorer refuses files larger than the drive's Recycle Bin, and drives with the bin turned off. It recycles through `SHFileOperationW` with `FOF_ALLOWUNDO|FOF_WANTNUKEWARNING`; the old VB call silently deleted such files permanently.
  - All PowerShell calls use UTF-8. Non-English names used to crash the Health Check.
  - Verdict severities: failing drives and disk or hardware errors are `high` (Fix soon), and info-only results show as Healthy.
  - PowerShell launches from the right folder.
  - Warning-level disk and hardware event IDs are collected.
- **Medium:**
  - Disk busy is 100 minus idle time, so it never exceeds 100% and history saves no longer fail.
  - The Stop button works on every Health Check.
  - The chart and AI evidence follow the newest diagnostic.
  - Performance Watch keeps a real 10-second schedule, Stop responds instantly, failed samples are retried, and the spike cap no longer ends a watch.
  - A cancelled admin prompt is not retried.
  - The registry viewer blocks the `ControlSet00x` alias and password-like values.
  - Storage Explorer: lstat junction detection, de-duplication, per-window selections and the diagnostic slot.
  - The ChatGPT fallback uses a general prompt with scan data as background only, makes no tool loop, and strips drive names.
  - The old console entry points go through the current assistant.
  - Claude gets a `get_latest_health_check` tool.
- **Small:** the Review-large-files button works, Windows 11 is named correctly, and Defender scan options open the scan page.

## Tests
`python -m unittest discover -p "test_*.py"` runs the full suite (108 tests): the handoff acceptance table, research labels and citations (Claude mocked, no cost), the no-key behavior, HTTP contracts, foreign-host rejection, the cross-window lock and collector mode.

## Known limitations
- Live research requires an Anthropic API key and is billed per use. Claude picks its own search terms, so the consent dialog shows the prompt and domains, not the queries.
- Charger wattage and connector cannot be read from Windows. The user must check the adapter label or Lenovo PSREF.
- The physical-port and network-port collectors are still not implemented. Those answers explain the limitation instead.
- Server-wide scan locking covers only `/api/scan`, not Performance Watch.
