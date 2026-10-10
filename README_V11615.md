# PC Medic AI 1.16.15: conversation and research fixes

## Root causes found in 1.16.14
- **Research returned useless results that looked like real ones.** Without a Brave key, `parts_research.py` used Bing's public RSS feed. The feed ignores the query and always returns the Lenovo homepage, Lenovo Support and Wikipedia. The UI then reported "Search complete · 8 candidate sources".
- **"Yes, research it" lost context.** The browser's yes-reply regex did not allow a comma.
- **Stale "Search online for parts" buttons** stayed visible during unrelated questions and researched the old part when clicked.
- **"What is my IP?" printed the IPv4 address twice.**
- **Two routing paths that disagreed.** About 10 regex shortcuts in `dashboard.html` ran before `intent_engine.py`. For example, the server classified "I need a new charger" as battery-health advice.

## Changes
- `intent_engine.classify(question, context)` is now the single routing path. It adds the intents `replacement_part` (with `part`), `open_tool` (with `tool`), `ports_clarify`, `research_confirm` and `research_decline`. Upgrade questions return `ram_upgrade`, `storage_upgrade` or `graphics_upgrade`. The browser sends `context.pending_research`, so short replies are interpreted against the open offer.
- `parts_research.py` was rewritten:
  - It searches live only through the Brave Search API (`BRAVE_SEARCH_API_KEY`). Without a key it says plainly that it did not search and returns direct manufacturer and retailer links.
  - It runs an OEM-first query, a retailer query and, for batteries, a part-number query, in parallel.
  - It drops homepages and off-topic hits. Every hit is labeled **Possible match** (mentions the exact model or part number) or **Unverified** (mentions only the manufacturer). Nothing is ever labeled verified.
- New endpoint `POST /api/parts-research-preview` returns the exact queries and shared fields. The consent dialog shows them before anything is sent.
- `hardware_advisor.inventory()` now also reports `ProductName` (for example "LOQ 15IRH8", from `Win32_ComputerSystemProduct.Version`) and `BatteryModels` (the OEM battery part number, for example "L22D4PA0"). The battery DeviceID is excluded because it contains a serial number.
- The UI clears stale offers when a new topic starts, disables research buttons while research runs, scrolls the results into view, and corrects the version label.

## Tests
`python -m unittest discover -p "test_*.py"` runs 30 tests: the handoff acceptance table, research filtering and labels, the no-key behavior and HTTP contracts.

## Known limitations
- Live product research requires a Brave Search API key set as a server environment variable.
- Charger wattage and connector cannot be read from Windows. The user must check the adapter label or Lenovo PSREF.
- The physical-port and network-port collectors are still not implemented. Those answers explain the limitation instead.
- Server-wide scan locking covers only `/api/scan`, not Performance Watch.
