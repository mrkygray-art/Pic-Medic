# PC Medic AI V1.11 — Device inventory improvements

- Search devices by name, class, driver manufacturer, or driver version.
- Filter by category and status: working, disconnected, needs attention, unknown.
- Distinguish phantom/disconnected devices (such as HDMI splitter monitors) from actual errors.
- Expand device cards to view driver details and safe guidance.
- Ask AI about a selected device pre-fills the single AI Console question; cloud sharing still requires explicit confirmation.
- The header distinguishes a device inventory scan from the main system health check.
- No driver installations, removals, updates, or privileged modifications.

Run `python -u dashboard.py` in this folder and open http://127.0.0.1:8765. Hard refresh after upgrade.
