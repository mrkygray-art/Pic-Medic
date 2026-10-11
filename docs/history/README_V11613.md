# PC Medic V1.16.13 — Opt-in online parts research (test)

Offline hardware identification remains the default. After a charger/RAM/storage research offer, click **Research online** and explicitly approve the web search. PC Medic submits only manufacturer, model and part category to a public search, not the serial number or diagnostic report. The results appear as clickable source links in the existing assistant view. You can optionally ask Claude or OpenAI to review the candidate source titles and links, with a second cloud consent prompt.

Search source: Brave Search API when `BRAVE_SEARCH_API_KEY` is configured; otherwise a best-effort public Bing RSS search. If neither returns usable sources, PC Medic displays retailer search links rather than inventing products. **Listings are never considered OEM compatibility proof.** Prices and stock are not guaranteed. The application does not perform purchases.

Test: Ask 'I need a replacement charger' or 'Can I upgrade my RAM?' then choose research, approve the web search, review links and optionally choose Claude/OpenAI. Requires internet access. The web search may be blocked by local network or providers.

No API keys are included. Run `python -u dashboard.py` from the extracted folder after stopping the previous server.
