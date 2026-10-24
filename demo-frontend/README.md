# Second Key · frontend

Big screen, Margaret's bank app, Emily's phone and the player phone for "Scam Margaret".
Right now it runs on a **mock** of the SpacetimeDB module so we can build and rehearse before the backend is done.

```bash
npm install
npm run dev            # http://localhost:5173
npm run build          # normal build for Vercel
npm run build:single   # one self-contained HTML file (backup for demo day)
```

## Screens (pick with the URL hash)

| URL | What it is | Who uses it on demo day |
|---|---|---|
| `#stage` | Big screen: balance, two scores, live call, money path, investigator, kernel decisions, leaderboard, QR | Projector |
| `#margaret` | Margaret's bank app (light, large type) | Optional second screen |
| `#emily` | Real Emily's phone, gets the bank's callback | Teammate on stage |
| `#player` | Join, secret role, pick a scam, chat with Margaret | Everyone who scans the QR |
| `#all` | Everything on one page | Rehearsal |

Press **H** to hide the nav and the demo controls. The demo dock has **Run full script** (IRS scam → cloned Emily → real Emily $400), one button per act, **Reset**, and **Turn sound on** (browsers need a click before audio).

Open `#stage`, `#emily` and `#player` in separate windows of the same browser: they stay in sync (BroadcastChannel + localStorage). Different devices won't sync until SpacetimeDB is wired in.

## Where things live

```
src/store/schema.ts     tables (match these to the SpacetimeDB module)
src/store/store.ts      MOCK reducers + sync  ← replace with SpacetimeDB client
src/store/kernel.ts     the hold/release rules (mirror of the Rust reducer)
src/store/signals.ts    mock signal extractor (regex)  ← Claude call replaces it, keep as fallback
src/store/margaret.ts   mock Margaret (rules)          ← Claude persona replaces it
src/store/actions.ts    orchestration + mock investigator agent (MCP tool calls)
src/store/director.ts   scripted 3-minute demo
src/screens/*           the four screens
src/components/*        panels, money path diagram
src/lib/sound.ts        synthesized ring / hold / blocked / released sounds
```

## Swapping the mock for SpacetimeDB (Person 1 + 4)

Every `dispatch({ type })` in `store.ts` is one reducer:

| Mock action | SpacetimeDB reducer |
|---|---|
| `join_player` | `join_player` |
| `start_call` | `start_call` |
| `add_message` (+ signals) | `add_message`, `add_signal` |
| `progress` | `update_session` |
| `initiate_transfer` | `initiate_transfer` (kernel rules run here) |
| `case_step`, `case_recommend` | `write_case_file` (called by the investigator via MCP) |
| `request_callback` | `request_callback` |
| `verify_callback` | `verify_callback` (only path to `release`) |

1. Generate TS bindings from the module (`spacetime generate --lang typescript`).
2. In `store.ts`, replace `dispatch` with `conn.reducers.<name>(...)` and fill `state` from table subscriptions (`onInsert` / `onUpdate`).
3. Delete the client-side kernel call in the reducer; the server decides.
4. Set `VITE_JOIN_URL` to the deployed `/#player` URL so the QR code works for phones.

## Swapping the mocks for Claude + Cartesia (Person 2 + 3)

- `callerSays()` in `actions.ts` is the seam: text in → Margaret reply + signals out. Replace the body with the Cartesia STT → Claude (Margaret) + Claude (extractor) pipeline. Keep the regex extractor as the offline fallback.
- `runInvestigator()` is the seam for the Agent SDK investigator. Its tool names already match the bank MCP server: `place_hold`, `get_account`, `list_payees`, `list_signals`, `get_trusted_contacts`, `request_callback`, `write_case_file`. No send-money tool.

## Branding

The bank in the mock is a made-up "Harbor Federal". Swap in your sponsor's name and colors in `MargaretApp.tsx` and `Callback.tsx` if the hackathon allows it.
