# PC Medic AI changelog

## 1.20.0 (2026-10-11)

- **Diagnostic coordinator** (`coordinator.py`, `POST /api/coordinate`): describe a problem ("my computer keeps freezing", "my PC restarts randomly", "it gets really hot", "Wi-Fi keeps dropping", "Chrome keeps crashing", "battery drains fast") and PC Medic runs an investigation:
  - it picks a playbook and runs that playbook's read-only routines in parallel (about 3–5 seconds);
  - it correlates the evidence with technician rules: graphics driver resets, drive errors and resets, file-system damage, WHEA hardware errors, thermal throttling, low memory with live RAM use, one program behind the hangs, blue screens and their driver, hard freezes, Wi-Fi drops, battery wear, low disk space, pending restarts, and what changed this week;
  - it ranks the next tests (Performance Watch, deep scan, memory test, Reliability Monitor, Health Check, devices, network, battery) as buttons.
  - Home shows plain findings; Technician shows the raw evidence.
- **The AI coordinates too:** Claude gets new read-only tools: `investigate_problem`, `get_what_changed`, `get_deep_scan`, `lookup_error_code` and `recommend_next_test`, whose pick becomes a button. In Claude mode it runs the investigation itself. In Smart mode, **Ask Claude to investigate further** hands Claude the evidence PC Medic already collected (stored server-side by ID, never with program names).
- **Warning signs in the Windows logs** (`system_checks` check `event_signals`, 30 days, under a second): graphics driver resets (Display 4101), disk errors (7/51/153), storage resets (129), NTFS damage (55), WHEA hardware errors, processor throttling (Kernel-Processor-Power 37), low memory (2004), service crashes, Wi-Fi drops (8003), app hangs (1002) and crashes (1000). Program names stay on this PC.
- **System Details** is now in Home mode too, with the manufacturer, model, computer type, and basic IP configuration (adapter, IPv4 and mask, gateway, DNS, DHCP). Technician mode adds BIOS, IPv6 and MAC. It's shown locally only and never sent to AI.
- **A window served by an older PC Medic** now says so ("This window shows PC Medic 1.19.0, but the PC Medic running behind it is…") instead of showing "Not found" on newer features like the deep scan.
- Routing: freezing, overheating, Wi-Fi drops, battery drain and repeated crashes or restarts start an investigation. "My computer is slow" still starts guided troubleshooting, and questions like "why did I get a blue screen?" still answer from the crash check.

## 1.19.0 (2026-10-11)

- **Error-code lookup** (`error_codes.py`, `GET /api/error-code`): ask "what does 0x80070643 mean?" (or "update error 8024200B") and PC Medic explains it offline: what happened and what to do.
  - It covers about 35 common Windows Update errors (WU, servicing and network codes), blue-screen stop codes and common program crash codes (such as 0xC0000005).
  - For other codes it uses Windows' own description, or the code's family.
  - The Windows Update check groups failures by error code with that explanation, and Technician mode shows each code's Windows name (for example `WU_E_UH_INSTALLERFAILURE`).
  - Deep checks has a **Windows Update errors** panel.
- **Deep checks** (Technician mode, new screen), all read-only:
  - **Security posture** (`system_checks` check `security`, no admin needed): Defender or another antivirus, signature age, Tamper Protection, firewall profiles, UAC level, Secure Boot, TPM (`tpmtool`), drive encryption, whether you sign in as an administrator, activation, Windows version support end date (Home/Pro dates in `SUPPORT_END`), last security update, Remote Desktop and SMB1. Each row is good, worth knowing, needs attention or problem, in plain and technical words. Home mode asks "Is my computer protected?" from a Tools card, and questions like "is my PC secure?" or "is Defender on?" route to it.
  - **Blue screens** (`bluescreen.py`): each stop code gets its name, what happened and what usually causes it (about 40 common codes), with the parameters and dump file in Technician mode. The deep scan reads the minidumps and finds the likely driver the way BlueScreenView does (a bug-check parameter that points into a driver, otherwise the first non-kernel driver on the crash stack), with the driver's maker and version. Anything that doesn't validate is dropped, never guessed.
  - **Deep scan as administrator** (`deep_scan.py`, `POST/GET /api/deep-scan`): one Windows UAC prompt starts a second, elevated copy of PC Medic (`--deep-scan`). It runs fixed read-only steps and writes `deep_scan.json`:
    - drive SMART counters (wear, temperature, power-on hours, uncorrected errors);
    - boot and shutdown times, and the apps, drivers and services that slowed startup;
    - DISM `/CheckHealth`, and optionally `sfc /verifyonly`;
    - the file-system dirty bit;
    - BitLocker protectors (never the recovery key), TPM and Secure Boot;
    - crash dumps and LiveKernelReports (hangs Windows recovered from).
  - The elevated copy only ever writes a file named `deep_scan.json`, never through a link. The scan holds the one-diagnostic-at-a-time slot, is off in demo mode, and Claude's copy drops app and service names. The technician report includes the security check and the latest deep scan.
- The crash check no longer reports "0 minidumps" when Windows wouldn't let it list them.
- **What changed?** (`timeline.py`, `GET /api/timeline`): the Today check saves one small snapshot a day (replacing earlier ones from the same day) and keeps them 90 days in `timeline.json`, local only and never sent to AI. Under the Today tiles, PC Medic compares today with about a week ago:
  - free space per drive (changes of 2 GB or 2% and up), battery health, new crashes or unexpected shutdowns ("the first in 21 days", "it came after Windows installed updates on Oct 8"), Windows updates, a restart still pending, and apps added to or removed from startup;
  - Home shows plain sentences, Technician the raw values; **Day by day** lists every day's changes;
  - demo mode never writes the timeline. The Today check now also reads startup apps (about half a second).
- **Battery report**: the battery check now reads Windows' runtime estimates and capacity history (`powercfg /batteryreport`):
  - how long a full charge lasts, now and when new ("about 1 h 29 min of active use (about 1 h 34 min when it was new)");
  - the trend since Windows started tracking, or since the battery was last replaced ("from 100% to 95% of new over 2 years and 8 months"), and when it will reach 80% at that pace;
  - the Today battery tile shows the runtime, and Home Tools has a **Battery report** card. Claude sees the runtime and trend, but not the battery's ID.
- **Greyed-out buttons say why**: a disabled button gets a tooltip and a note under its row saying what turns it on ("Run a Performance Watch first…", "A Health Check is running…"). Buttons that are normally off while idle, like Stop, only get the tooltip.
- **Add or remove programs** in Tools: **Installed Apps** (Windows 11 Settings, `ms-settings:appsfeatures`) and the classic **Programs and Features** (`appwiz.cpl`) in Technician mode, and an **Uninstall apps** card under "Speed it up and free space" in Home mode. Like every Windows tool, they're allowlisted and ask before opening. PC Medic never uninstalls anything itself. Answers that mention Add or Remove Programs, Apps & features or uninstalling an app link to the tool.
- **Google sign-in** (`google_auth.py`, Settings > Google account): PC Medic's free AI questions now need a Google sign-in. Your own Anthropic or OpenAI key never does.
  - Sign-in uses Google's flow for desktop apps: the page opens in your default browser and returns to a one-time listener on 127.0.0.1 (PKCE, random state, 5-minute limit).
  - Only `openid email` is requested. PC Medic keeps the account ID and email in Windows Credential Manager and throws away Google's tokens. Nothing about the PC is sent.
  - The 10-question count is still per Windows account, so signing in with another Google account doesn't reset it.
  - Needs the Google Cloud "Desktop app" OAuth client in `google_client.json`, the file Google's console downloads. It's gitignored, because Google disables client secrets found on public GitHub, and the build bundles it. `PCMEDIC_GOOGLE_CLIENT_ID`/`PCMEDIC_GOOGLE_CLIENT_SECRET` override it. Without it, Settings says sign-in isn't set up and the trial stays off.
- The GitHub repository is now `mrkygray-art/pc-medic` (it was `Pic-Medic`). Update checks use the new name. Copies of 1.18.0 and 1.18.1 still find updates through GitHub's redirect.

## 1.18.1 (2026-10-11)

- A window left open while PC Medic restarts now says "PC Medic was restarted. Press F5 to reload this window" instead of failing with a confusing error (its old code and token no longer match the server).
- A Health Check failure is also logged to the browser console with the full error.

## 1.18.0 (2026-10-10)

Redesign, phase 1: a Windows 11 look and two audiences, home users and technicians.

- **Home and Technician modes:**
  - On first launch PC Medic asks which mode to use. The header switch changes it at any time, and the choice is remembered.
  - Home shows Today, Fixes, Tools and Settings. Technician shows every screen.
  - The same evidence is shown in two voices. `/api/check` returns a `technical` line next to the plain summary (`system_checks.describe_technical`), and troubleshooting findings carry `tech` text (`explanation_tech`).
- **Today screen** (`today.py`, `GET /api/today`, cached 5 minutes, `?refresh=1`):
  - A quick parallel check when PC Medic opens (about 3 seconds): battery, disk health, crashes, updates, pending restart and a 3-second performance sample.
  - It shows a verdict and five tiles (Speed, Storage, Battery or Power, Updates, Stability). Each tile is good, worth knowing, needs attention or problem.
  - Clicking a tile asks PC Medic about it. A full drive opens Storage Explorer.
- **Conversation:**
  - Your question appears as a chat bubble above the answer.
  - Each answer is labeled with its source, for example "Answered by PC Medic · on this PC", "Claude · read-only checks on this PC", "ChatGPT (OpenAI)" or "Claude · web research". Archived turns keep the label.
- **Fixes:** troubleshooting history in plain words, with Continue for open cases.
- **Tools for home users:** grouped plain-language cards (Check my computer, Speed it up and free space, Stay safe and up to date, Get help). Windows tools still use the allowlist and confirmation. Technician mode keeps the full Windows tools list and Advanced tools.
- **App window:** `dashboard.py` opens PC Medic in a Microsoft Edge app window, falling back to the default browser. `--no-window` skips this.
- **Look:**
  - Windows 11 (Fluent) styling with Segoe UI Variable, a light navigation pane, white cards and the `#005FB8` accent.
  - Dark mode follows Windows and is remembered. The page has a window icon.
- **Fix:** the technical battery line no longer fails when Windows doesn't report a capacity.
- **Fix:** the Health Check stopped partway with "Cannot set properties of null" since 1.17.0. The 1.17.0 cleanup removed `#evidence-note`, but the findings code still wrote to it. A new test checks that every element ID the page script uses exists.

### Windows installer (first release)
- `packaging/build.ps1` builds `PCMedic-Setup-<version>.exe`:
  - It runs the tests, draws the icon (`make_icon.py`), builds a windowed one-folder app with PyInstaller (`pcmedic.spec`, with version info), then packs it with Inno Setup (`PCMedic.iss`).
  - The installer is per-user, with no admin prompt. It installs to `%LOCALAPPDATA%\Programs\PC Medic` and adds a Start menu shortcut, an optional desktop shortcut and an uninstaller.
  - No API key is ever bundled.
- **App lifecycle:**
  - Opening the installed app again shows the running copy (`/api/ping`, `find_running`).
  - Windows ping `/api/window`, and the app stops about 30 s after its last window closes (`--exit-when-closed` from source). It never stops while a diagnostic is running.
  - The windowed .exe writes its log to `%LOCALAPPDATA%\PC Medic\pcmedic.log`, since it has no console.
- Tested on Windows 11 build 26300:
  - Silent install.
  - Today screen, a disk-health question, and a full Health Check through the packaged collector.
  - Self-exit after the window closes.
  - Upgrading over an existing install.
  - Uninstall (saved data kept).
- The installer is not code-signed yet, so SmartScreen shows a warning on first run.

## 1.17.0 (2026-10-10)

First release maintained with Claude Code, after the ChatGPT-built 1.16.14 prototype.

### Guided troubleshooting, Settings and reliable AI
- **Guided troubleshooting** (`troubleshooter.py`, `/api/troubleshoot/*`):
  - "Slow" questions start a case. It asks when the PC is slow (startup, browsing, gaming, all the time), or reads it from the question.
  - It measures CPU, memory and disk (PDH), per-app CPU, disk and memory, enabled startup apps (StartupApproved), disk health and space, uptime and pending restarts, and the power plan.
  - It explains the evidence in plain English and recommends one action with steps and a button to open the right Windows page.
  - After "I've done it" it measures again, compares with the first check, asks how the PC feels, and saves the outcome to `cases.json`.
  - Open cases can be continued after a restart. History appears in the technician report.
- **Settings tab and keys** (`settings.py`): keys are checked with the provider and stored in Windows Credential Manager. A key in the environment counts as the user's own. A trial key allows 10 AI questions per Windows account, then the user is asked for their own key.
- **Update checks:** GitHub Releases check with a download banner, off until `PCMEDIC_UPDATE_REPO` is set.
- **Reliable Claude chat:** questions run as background jobs with live progress and Cancel. Tools run in parallel with timeouts and per-turn caching, the SDK retries transient errors, and a turn deadline makes Claude answer with what it has.
- **Cleanup and small fixes:**
  - Removed the old hidden console, the old Claude path and `/api/ask`.
  - CPU, disk and memory sampled in-process with PDH; per-sample PowerShell inflated CPU.
  - OneDrive online-only files are skipped in Storage Explorer.
  - "AI-guided Health Check" is now "Health Check".
  - Version 1.17.0 in `version.py`; old READMEs moved to `docs/history`.

### Root causes found in 1.16.14
- **Research returned useless results that looked like real ones.** Without a Brave key, `parts_research.py` used Bing's public RSS feed. The feed ignores the query and always returns the Lenovo homepage, Lenovo Support and Wikipedia. The UI then reported "Search complete · 8 candidate sources".
- **"Yes, research it" lost context.** The browser's yes-reply regex did not allow a comma.
- **Stale "Search online for parts" buttons** stayed visible during unrelated questions and researched the old part when clicked.
- **"What is my IP?" printed the IPv4 address twice.**
- **Two routing paths that disagreed.** About 10 regex shortcuts in `dashboard.html` ran before `intent_engine.py`. For example, the server classified "I need a new charger" as battery-health advice.

### Changes
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

### Follow-up bug fixes
- **DNS rebinding (security).** Any website could resolve its own name to 127.0.0.1, read the request token from `/api/report` and send commands: open tools, read the registry, recycle files, run paid research. Every request must now use Host `127.0.0.1:<port>` or `localhost:<port>`, and any Origin must match.
- **The assessment text was treated as the user's symptom.** Missing braces in `healthCheck()`, plus the same pattern in `updateAssessment()`, copied PC Medic's previous answer (for example charger research) into the Health Check as "Your reported symptom". `userSymptom` now comes only from the Ask box, and a manual Health Check starts with none.
- **The scan would break in a packaged .exe.** It relaunched `sys.executable collector.py`. A frozen build now relaunches itself with `--run-collector`. Scan data and history go to `%LOCALAPPDATA%\PC Medic` when frozen.
- **Diagnostics could overlap across windows.** A server-side lease (`POST /api/activity`, renewed by each sample, expiring after 90 seconds) now allows one Health Check or Performance Watch at a time across all windows. The other window shows an amber "blocked" message.

### New features
- **Chat history.** Earlier questions and answers stack as chat bubbles above the current answer. The answer box is read-only output.
- **Seven read-only checks** (`system_checks.py`, `GET /api/check?name=`): battery wear (`powercfg /batteryreport`), disk health and free space, blue screens and unexpected restarts (30 days), Windows Update failures (30 days), startup apps, pending restart, and listening network ports. Questions route to them through the `system_check` intent. `for_cloud()` removes process names, app names and duplicates before Claude sees anything.
- **Claude investigation mode** (`assistant.py`, `POST /api/assistant`). An "Answer with: Offline | Claude" switch, with Offline as the default. Claude (`claude-opus-5-5`, override with `PCMEDIC_ASSISTANT_MODEL`) chooses among read-only tools: computer overview, a system check, recent errors, performance snapshot, network status and web search. Conversations are held on the server, so follow-ups keep context. Consent is asked once per page session. Offline fallbacks (howto, clarify) offer "Ask Claude instead". A live test cost about $0.10–0.25 per question.
- **Technician report** (`report.py`, `POST /api/technician-report`). One printable HTML page with computer details, Health Check findings, current checks, recent errors, the session's questions and answers, and editable technician notes. Print / Save as PDF. All text is HTML-escaped.

### Laptops, desktops and shared computers
- **Computer type.** `hardware_advisor.identify()` reads the chassis type and `PCSystemType` and sets `DeviceType`: laptop, desktop, all-in-one, virtual or unknown. On desktops, charger questions get power-supply guidance and research, battery questions explain the CR2032 coin cell, and graphics and storage advice covers PCIe cards and drive bays. Claude and the technician report also see the type.
- **Custom-built PCs.** When the manufacturer or model is a placeholder ("To Be Filled By O.E.M.", "System Product Name"), the motherboard becomes the identity (`IdentitySource: motherboard`). Parts research accepts maker names with commas and knows the Gigabyte, ASRock and Biostar sites.
- **One Windows account only** (`local_security.py`). Each request's connection is matched to its process through Windows' TCP table, and that process's account must match the server's. Anything unverifiable is refused. The server binds its port exclusively, so no other account can bind on top of it, and moves to the next free port if 8765 is taken.

### Answering any question
- **Answer modes:** Offline only, **Smart** (the default) and Claude. In Smart mode the built-in engine answers when it can. Questions it does not recognize (`clarify` and `howto` intents) go to Claude, or to ChatGPT if only an OpenAI key exists, after a one-time consent. With no AI service, a problem description starts the AI-guided Health Check. Otherwise PC Medic shows Ask Claude, Ask ChatGPT, Run Health Check and Run Performance Watch buttons.
- **Gaming:** "Can this run games?" is answered offline from the strongest real graphics adapter (virtual display drivers are ignored), plus RAM and laptop power advice.
- **API keys:** the server reads `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from the user's saved environment (`HKCU\Environment`) when the launching window predates `setx`.
- **Startup:** the answer box starts empty. The last Health Check summary appears only after a Health Check runs.
- **Known limitation:** the ChatGPT path reuses the original `ai_engine` analysis prompt. It cannot run checks or search the web, and it frames answers around the latest Health Check, so Claude gives much better general answers.

### Review fixes (four parallel reviews of the inherited features)
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

### Tests
`python -m unittest discover -p "test_*.py"` runs the full suite (108 tests): the handoff acceptance table, research labels and citations (Claude mocked, no cost), the no-key behavior, HTTP contracts, foreign-host rejection, the cross-window lock and collector mode.

### Known limitations
- Live research requires an Anthropic API key and is billed per use. Claude picks its own search terms, so the consent dialog shows the prompt and domains, not the queries.
- Charger wattage and connector cannot be read from Windows. The user must check the adapter label or Lenovo PSREF.
- The physical-port and network-port collectors are still not implemented. Those answers explain the limitation instead.
- Server-wide scan locking covers only `/api/scan`, not Performance Watch.

## Earlier versions

Notes for 1.6 through 1.16.14 are in [docs/history](docs/history/).
