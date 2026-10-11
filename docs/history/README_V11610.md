# PC Medic V1.16.10 — Conversation and research handoff test

Changes from V1.16.9:
- Clarifies ambiguous 'ports' as physical ports, network service ports, or RAM slots rather than inventing a count.
- RAM/storage/graphics upgrade explanations offer an explicit cloud research handoff or stay-offline choice.
- Preserves upgrade context in the AI investigation prompt, and asks for Claude/OpenAI selection and existing explicit consent before sending.
- Prevents the research prompt from being replaced by the generic assessment prompt.

Limits: Claude/OpenAI APIs connected to this build do not inherently have live web browsing. The prompt explicitly requests uncertainty disclosure and no invented prices/links. No retailer search API, TCP/UDP port inventory collector, or OEM compatibility verifier has been added. The existing cloud privacy confirmation remains in place. Windows runtime testing is required.
