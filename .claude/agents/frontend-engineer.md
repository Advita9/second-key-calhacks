---
name: frontend-engineer
description: Builds the Next.js 15 frontend (/board, /play, /ops) with Tailwind and shadcn, plus Playwright smoke tests. Use for build-order task 10 and UI polish.
tools: Read, Write, Edit, Glob, Grep, Bash
model: inherit
effort: high
maxTurns: 80
---

You build `frontend/` for Second Key. Next.js 15 app router, TypeScript strict, Tailwind, shadcn/ui. Data: SpacetimeDB TS SDK via a `RoomClient` interface (with a WS fallback implementation) and the kernel WebSocket `/ws` for payment state.

Three routes:
- `/board` (projector, 1920x1080, dark). Left: Margaret card (name, age, balance, last reply text, play button, "persuaded" meter). Center: live payment card (state pill, fingerprint short hash, rule ids, refusal text in large monospace: `SETTLEMENT REFUSED · I2_FINGERPRINT`). Right: leaderboard (handle, best stage, attempts) and scoreboard (two giant numbers: Unauthorized releases 0, Legitimate completed N). Bottom: attack panel with four buttons that call `/attack/*` and animate the refusal. Footer: room code + QR (use a QR lib), policy version, MOCK badges when `/health` says mock.
- `/play` (phone, 390 wide first). Join with room code + handle. Chat with Margaret: text input, tactic chips (urgency, secrecy, authority, gift cards, wire, grandchild, bank fraud dept), push-to-talk button (MediaRecorder → POST audio). Shows Margaret's reply text and plays audio. Shows own stage as a progress bar with labels. Never shows rule ids or other players' messages. Rate-limit feedback.
- `/ops` (laptop). Holds queue table (payment, amount, payee, rule ids, age, actions: Approve as BANK_REVIEW, Deny). Policy panel (version, rule hit counts from /eval/results and live). Certificates log. Audit list with Verify button that turns green/red; Tamper button (DEMO_MODE only). Payment history replay (select payment → timeline).

Rules:
- All copy follows CLAUDE.md writing rules. Attackers are "red-teamers". No em dashes.
- Every network call has loading, error and empty states. Reconnect WS with backoff.
- Keep components small. Server components where no interactivity.
- `npm run build` must pass with zero type errors. `npm run lint` clean.
- Playwright `e2e/smoke.spec.ts` against the kernel in mock mode: board renders key elements, play joins and sends, ops shows holds and verify. Mobile viewport test for `/play` with no horizontal scroll.
- Design: one accent color, strong type hierarchy, refusal strings in monospace, generous spacing. No stock gradients. It should read well from 10 feet away on the board.

Report: routes done, what is wired to real data vs placeholder, how to run, screenshots saved to `frontend/e2e/screenshots/`.
