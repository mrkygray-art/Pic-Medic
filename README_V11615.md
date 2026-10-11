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

## Tests
`python -m unittest discover -p "test_*.py"` runs 42 tests: the handoff acceptance table, research labels and citations (Claude mocked, no cost), the no-key behavior, HTTP contracts, foreign-host rejection, the cross-window lock and collector mode.

## Known limitations
- Live research requires an Anthropic API key and is billed per use. Claude picks its own search terms, so the consent dialog shows the prompt and domains, not the queries.
- Charger wattage and connector cannot be read from Windows. The user must check the adapter label or Lenovo PSREF.
- The physical-port and network-port collectors are still not implemented. Those answers explain the limitation instead.
- Server-wide scan locking covers only `/api/scan`, not Performance Watch.
