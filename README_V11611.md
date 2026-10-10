# PC Medic V1.16.11 — Conversational Workflow Repair (test)

- Compound RAM/SSD/GPU upgrade and shopping questions are handled as hardware investigations, not generic definitions or Performance Watch requests.
- Research offer includes actual buttons for cloud handoff or staying offline.
- Short follow-ups like "yes, research it" and "no thanks" are interpreted against the pending upgrade research.
- The original hardware question and inventory are retained in the research prompt; research requires provider selection and existing cloud consent.
- Clears the question input after submission and does not insert the generated research prompt into that input.
- Cloud API access does not imply live web browsing. Do not rely on unverified product compatibility or prices.

Test: ask "What RAM do I have, can I upgrade, and where can I buy it?"; click Research; cancel and repeat; ask "yes, research it"; verify no automatic cloud transfer. Keep your prior working version as backup.
