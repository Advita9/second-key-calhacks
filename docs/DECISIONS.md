# Decisions

One entry per decision the agent made without a human. Newest first. Format: time, decision, why, how to undo.

- 2026-10-23 21:40 (Armaan + Claude) Hybrid architecture: Python FastAPI kernel keeps the Hypothesis tests; SpacetimeDB owns room, turns, leaderboard; Node bridge connects them. Why: no Python SDK for SpacetimeDB, and the kernel's correctness story is stronger in Python with property tests. Undo: move policy engine into reducers (TypeScript) if the SpacetimeDB judge needs it.
- 2026-10-23 21:40 (Armaan) No hardware. Why: team is not familiar with it, and the memorable moment is the live red-team, not a device.
- 2026-10-23 21:40 (Armaan) Game framing is "stress-test Margaret's bank"; players are red-teamers; scoring by stage reached, never by text. Why: responsible-design review.
