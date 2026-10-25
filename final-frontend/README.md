# Second Key · final frontend

`frontend`'s working features (kernel REST and WebSocket, room client, Cartesia voice, attacks, ops) with `demo-frontend`'s screen ideas (big-screen layout, money path, Margaret's moods, phone frames), restyled to sit next to hyphenate.ai: white surfaces and Hyphenate's crimson (`#790005`), set in Geist.

One rule drives the look: **crimson means authority**. The policy engine, certificates, verifier, audit log and the kernel's decision panel are crimson. Everything a model or a person can talk to (Margaret, the extractor, Cartesia, the phones) is white or stone. The colour itself says "the model proposes, the kernel disposes".

```bash
npm install
npm run dev          # http://localhost:3001, kernel expected at http://localhost:8000
npm run rehearse     # mock kernel + dev server, for practice without the backend
npm run build
```

## Screens

| Route | What it is | On demo day |
|---|---|---|
| `/` | Pitch page: hero, interactive architecture, "try to break it" with QR + attack cards, Cartesia voice flow, three rules | Laptop, before the live part |
| `/architecture` | The architecture alone, full screen | Projector while you explain |
| `/board` | Live board: Margaret (mood follows the call), where the money is, the kernel's decision with rule names, attack buttons, QR, scoreboard, leaderboard, debrief | Projector |
| `/play?room=DEMO` | Phone: join, chat, hold-to-talk (Cartesia speech-to-text), Margaret's voice (Cartesia TTS), tactic chips, stage bar | Everyone who scans the QR |
| `/ops` | Bank operator: holds queue, approve/cancel, scripted attack, reset Margaret, legit payment, end/resume round, policy, certificates, payment history, audit verify/tamper | Teammate's laptop |

Board and ops accept `?token=OPS_TOKEN` (stored per browser) and `?room=CODE`. `/board?debrief=1` opens the debrief.

## The architecture view

`src/components/arch/model.ts` holds one model drawn two ways:

- **Five steps**: the call → the model → the rules → the second key → the bank. This is the simple money path from `demo-frontend`.
- **Full system**: every box from the system diagram (phones, Cartesia, SpacetimeDB room, bridge worker, the kernel service with Margaret / room session / extractor, the authority core with policy, HELD, DENIED, ELIGIBLE_TO_SUBMIT, certificate, verifier, SETTLEMENT REFUSED, the audit log, the bank operator, SUBMITTED, Capital One Nessie).

Every full node belongs to a simple step, so the six scenarios (grandchild scam, real roofer bill, prompt injection, payee swap, replay, family self-approval) play in both views. Click any box to see what it does and what it **cannot** do.

## Margaret's moods

`public/margaret/{calm,worried,distressed,angry,happy}.png`, backgrounds removed. `moodFor()` in `src/components/margaret/Margaret.tsx` picks one from the last event: a fresh call is calm, pressure is worried, persuaded is distressed, a hold/deny/refusal is angry (she caught the scam), a submitted payment is happy. The kernel never reads her mood.

## Wiring (unchanged from `frontend`)

- `src/lib/kernel/*`: REST client (through the `/kernel` rewrite), operator token, WebSocket with backoff.
- `src/lib/room/*`: memory room (kernel routes) or SpacetimeDB (`NEXT_PUBLIC_ROOM_BACKEND=spacetime` + generated bindings in `src/module_bindings`), with automatic fallback.
- Voice: `PushToTalk` posts the clip to `/rooms/{room}/stt`; Margaret's `audio_url` plays on the board and the phone.
- QR: set `NEXT_PUBLIC_PLAY_ORIGIN=http://<laptop LAN IP>:3001` so phones can reach the laptop when the board runs on localhost.

See `.env.example` for every variable.

## Mock kernel

`scripts/mock-kernel.mjs` answers the same routes and WebSocket messages with rule-based Margaret and policy. `/health` reports every provider as `mock`, and the UI labels them that way, so it can't be mistaken for the real system. Use it for rehearsal only.
