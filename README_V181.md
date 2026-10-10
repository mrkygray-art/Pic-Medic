# PC Medic AI 1.8.1 — Findings-to-AI workflow patch

- Automatically selects all rule-based findings from the latest available system scan, including informational findings.
- Automatically prepares an editable question summarizing the selected findings.
- Selecting/deselecting findings updates the prepared question unless the user has written a custom question.
- Keeps the Offline / Claude / OpenAI engine selector and explicit confirmation before every cloud request.
- No cloud request occurs when findings are selected or a question is populated.
- The local health check remains manually initiated.

## Run

In PowerShell, from this directory:

```powershell
python -u .\dashboard.py
```

Then visit http://127.0.0.1:8765 and hard-refresh the browser.

## Test

Run `python -m unittest discover -p 'test_*.py' -v`.

Expected: The existing scan's findings are preselected on load, the AI question describes them, and unchecking a finding changes the proposed question. Selecting Claude or OpenAI does not transmit anything until the user clicks Investigate and explicitly approves the request.
