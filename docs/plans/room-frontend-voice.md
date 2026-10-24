# Plan: room, frontend, voice (build-order 9 to 11)

Architect agent, 2026-10-23 23:10. Facts: CLI config has `default_server = "maincloud"` so every command needs `--server local`; SpacetimeDB holds port 3000, so Next runs on 3001; Node 22, `say` and `afconvert` present. Lead amendments at the bottom override.

## 1. Files

**spacetime/** (spacetime-engineer)
- `src/index.ts` schema, tables, reducers, `my_outcomes` view, `init` stores owner.
- `package.json` deps `spacetimedb@2.13.0`, build `tsc --noEmit` (keep; publish builds itself). `tsconfig.json` per research (ESNext, lib ES2021+dom, isolatedModules).
- `scripts/gen-bindings.sh` generates into `bridge/src/module_bindings/` and `frontend/src/module_bindings/`; bindings are committed so builds never need the CLI.

**bridge/** (spacetime-engineer)
- `src/index.ts` worker loop. `src/kernel.ts` typed HTTP client. `src/token.ts` persist token + write `bridge/.identity.hex`. `src/tools/submit_turn.ts` tiny attacker client for e2e. `package.json` deps `spacetimedb@2.13.0`, `tsx`; `dev` = `tsx src/index.ts`.
- `tests/e2e/test_room.sh` (repo root, chmod +x).

**backend/** (spacetime-engineer owns these two; kernel-engineer owns the rest)
- `kernel/room_memory.py` pure `RoomStore` (dicts, same tables, same limits as reducers).
- `api/room_ws.py` `APIRouter`: room REST additions + `/ws` snapshot push.

**backend/kernel/voice/** (voice-engineer)
- `__init__.py` docstring ("Voice is evidence, not identity. Nothing here identifies a speaker."), `types.py`, `cache.py`, `mock.py`, `cartesia.py`, `factory.py`.
- `backend/api/voice_routes.py` `APIRouter`: `/audio/{hash}.wav`, `POST /rooms/{room}/stt`.
- `scripts/prerender_audio.py`; `fixtures/audio/` recorded `tts_bytes.wav`, `stt_response.json`, `clip.webm`.
- `backend/tests/voice/*`.

**frontend/** (frontend-engineer)
- Next 15 scaffold, `src/lib/room/{types,spacetime,ws,index}.ts`, `src/lib/kernel/{rest,ws}.ts`, `src/app/{board,play,ops}/page.tsx`, components per route incl. `components/play/PushToTalk.tsx`, `playwright.config.ts`, `e2e/smoke.spec.ts`, `src/module_bindings/` (generated, committed).

Lead wires `include_router` lines in `api/main.py` and the dev.sh TODOs; engineers do not touch those files.

## 2. Interfaces

**Module** (column types):
```
room(id: string PK = code, code: string unique, status: string, policyVersion: string, createdAt: timestamp)
player(identity: Identity PK, roomId: string idx, handle: string, role: string, joinedAt: timestamp, lastTurnAt: timestamp)
turn(id: u64 PK autoInc, roomId: string, player: Identity, text: string, audioUrl: string, status: string idx, createdAt: timestamp)
margaret_reply(id: u64 PK autoInc, turnId: u64 unique, text, audioUrl, persuaded: bool, createdAt)
outcome(id: u64 PK autoInc, turnId: u64 unique, player: Identity idx, roomId, stage: u8, paymentId: string, decision: string, ruleIds: array<string>, refusal: string)
leaderboard(player: Identity PK, roomId idx, handle, bestStage: u8, attempts: u32, lastAt)
scoreboard(roomId: string PK, unauthorizedReleases: u32, legitCompleted: u32, attempts: u32)
audit_mirror(seq: u64 PK, roomId, kind, hash, prevHash, ts: string)
config(id: u32 PK, ownerIdentity: Identity, workerIdentityHex: string)   // private table
view my_outcomes(public) -> array<{turnId: u64, stage: u8, decision: string}>  // filter outcome.player == ctx.sender; no ruleIds, no refusal
reducers: create_room(code) join_room(code, handle) submit_turn(roomId, text) set_worker_identity(hex) [owner only]
  worker only: claim_turn(turnId) record_reply(turnId,text,audioUrl,persuaded) record_outcome(turnId,stage,paymentId,decision,ruleIds,refusal) record_legit_completed(roomId) mirror_audit(roomId,seq,kind,hash,prevHash,ts)
  operator only: set_room_status(roomId,status) reset_room(roomId)
```
Identity stored as hex string so `spacetime call` can pass it. Optional columns use `''` sentinel (avoid `t.option` encoding questions).

**Bridge loop**: connect(token file) -> `onConnect` write hex -> subscribe `SELECT * FROM turn WHERE status='queued'` -> `onInsert`: if `done.has(id)` skip; `claimTurn`; `POST ${KERNEL_URL}/rooms/{roomId}/turns {turn_id, player_id: hex, text}` (10s timeout); `recordReply`; `recordOutcome`; if `stage==100` nothing extra (scoreboard handled in reducer); `GET /audit?limit=50` -> `mirrorAudit` for seqs > lastSeq. Kernel error -> `recordOutcome(stage 10, 'HOLD', [], 'kernel unavailable, fail closed')`. Bridge never imports or calls `/payments/*`.

**RoomClient (TS)**:
```ts
type Stage = 0|10|40|60|70|90|100;
interface RoomSnapshot { room: RoomRow|null; players: PlayerRow[]; replies: ReplyRow[]; outcomes: OutcomeRow[]; myOutcomes: OutcomePublic[]; leaderboard: LeaderboardRow[]; scoreboard: ScoreboardRow|null; audit: AuditMirrorRow[] }
interface RoomClient {
  readonly backend: 'spacetime'|'memory';
  connect(o: {roomCode: string; role: 'attacker'|'board'|'ops'}): Promise<void>;
  join(handle: string): Promise<{ playerId: string }>;
  submitTurn(text: string, audioUrl?: string): Promise<void>; // throws RoomError{code:'RATE_LIMIT'|'TOO_LONG'|'CLOSED'}
  subscribe(cb: (s: RoomSnapshot) => void): () => void;
  myId(): string|null; close(): void;
}
export function makeRoomClient(): RoomClient  // NEXT_PUBLIC_ROOM_BACKEND
```

**Kernel additions (memory mode and voice)**:
```
POST /rooms/{room}/join {handle} -> {player_id, player_token}
POST /rooms/{room}/turns  JSON (bridge) or multipart text?+audio (player, header X-Player-Token) -> api.md shape + transcript?
GET  /rooms/{room}/snapshot?role=&player_id= -> RoomSnapshot (attacker role strips ruleIds/refusal/others' outcomes)
POST /rooms/{room}/stt multipart audio -> {transcript, audio_url, provider, is_mock}
GET  /audio/{hash}.wav
WS /ws?room=&role=&player_id= pushes {type:"room", snapshot} on every change plus api.md payment/margaret/attack messages
```
```python
class RoomStore:  # pure, no I/O
    def create_room(code) -> RoomRow; join(code, handle, now) -> PlayerRow
    def submit_turn(room_id, player_id, text, now) -> TurnRow   # raises RoomError(TOO_LONG|RATE_LIMIT|CLOSED); 400 chars, 3s
    def record_reply(...); record_outcome(...); record_legit_completed(room_id); mirror_audit(...)
    def snapshot(room_id, role: Role, player_id: str|None) -> RoomSnapshot  # strips for attacker
```
**Voice (Python)**:
```python
class Transcript(BaseModel, frozen=True): text: str; provider: str; is_mock: bool; duration_s: float|None
class TTS(Protocol): name: str; def synthesize(self, text: str, voice_id: str) -> Path
class STT(Protocol): name: str; def transcribe(self, audio: bytes, mime: str, *, hint: str|None=None) -> Transcript
def audio_key(text: str, voice_id: str) -> str          # sha256(text + "\x00" + voice_id)
class AudioCache: __init__(root: Path); path(key) -> Path; get(key) -> Path|None; put(key, wav: bytes) -> Path
class MockTTS(cache, say_bin="/usr/bin/say"); def silent_wav(seconds=1.0, rate=24000) -> bytes
class CartesiaTTS(api_key, cache, *, voice_default, model_id="sonic-3.6", sample_rate=24000, client: httpx.Client|None=None)  # threading.Lock around POST
class MockSTT(); class CartesiaSTT(api_key, *, model="ink-whisper", client=None)
def make_tts(env) -> TTS; def make_stt(env) -> STT    # TTS_PROVIDER/STT_PROVIDER; "cartesia" without key -> mock + warning
```

## 3. Tests first
- `spacetime`: `npm run build`; e2e: worker reducers from non-worker identity throw `SenderError` (I4: only the bridge, never a client, writes outcomes); `my_outcomes` row has no `ruleIds` key (PRD secrecy); `submit_turn` 401 chars and 2nd turn within 3s rejected.
- `bridge`: grep test: `bridge/src` contains no `/payments` or `release` (I1, I4 by construction); kernel 500 -> outcome stage 10 HOLD (fail closed).
- `tests/e2e/test_room.sh`: outcome row within 10s; memory branch via REST snapshot.
- `backend/tests/unit/test_room_memory.py`: rate limit, length, attacker snapshot has no rule_ids; mirror_audit hashes equal `GET /audit` hashes (I7 mirror is faithful).
- `backend/tests/voice/`: `test_cache.py` same text+voice same key, different voice different key; `test_mock_tts.py` returns RIFF header, silent fallback when `say` missing; `test_cartesia_tts.py` with `httpx.MockTransport` asserts URL, Bearer, `Cartesia-Version: 2026-08-14`, body, lock serialization; `test_cartesia_stt.py` multipart `ink-whisper`; `test_fail_closed.py` STT exception -> `Transcript("[inaudible]", is_mock=True)`, TTS exception -> turn still answers with `audio_url=None`; `test_no_identity.py` `Transcript` has no speaker/identity field.
- `frontend/e2e/smoke.spec.ts`: board elements, play join+send, ops holds+verify button, MOCK badge from `/health`, 390x844 `scrollWidth <= clientWidth`.

## 4. Mock boundary
Without keys everything runs: `ROOM_BACKEND=memory`, `MOCK_EXTRACTOR=1`, `TTS_PROVIDER=mock` (`say`), `STT_PROVIDER=mock` (returns `hint` or `[inaudible]`). Real switches: `ROOM_BACKEND=spacetime` + `SPACETIME_URI`/`SPACETIME_DB`; `TTS_PROVIDER=cartesia`/`STT_PROVIDER=cartesia` + `CARTESIA_API_KEY` + `CARTESIA_VOICE_ID`. Frontend: `NEXT_PUBLIC_ROOM_BACKEND`, `NEXT_PUBLIC_KERNEL_URL`, `NEXT_PUBLIC_SPACETIME_URI`. `/health.mode` adds `stt`, UI badges read it.

## 5. Risks
- **Worker identity bootstrap.** Owner-gated: `init` stores `ctx.sender` (publisher) in `config`; `set_worker_identity` requires `ctx.sender === ownerIdentity`; `dev.sh` starts the bridge, waits for `bridge/.identity.hex`, runs `spacetime_cli call --server local --yes second-key set_worker_identity '"<hex>"'`. Docs: "The database owner authorizes one worker identity at deploy. Bank-side outcomes are written only by that worker." Verify in a probe that `init` sees the publisher as sender; fallback is first-come with the window closed inside dev.sh before `/play` is shared.
- **Playwright webServer**: two entries, `reuseExistingServer: true`, kernel on 8000 with memory env, frontend `test -f .next/BUILD_ID || next build; next start -p 3001`, timeout 180s. Port 3000 belongs to SpacetimeDB.
- **Bindings generation in CI**: commit generated bindings; `gen-bindings.sh` is a dev step; if absent, `SpacetimeRoomClient` is behind a dynamic `import()` so `next build` still passes.
- **Next 15 + React 19 + shadcn**: install only button, card, badge, input, table; if peer errors, `npm i --legacy-peer-deps`; QR via `qrcode.react@4`.
- **`say` latency** (1 to 3s per line): pre-render all fixture lines at dev.sh start; synthesize in a thread; the turn response never waits more than 4s, returns `audio_url=null` otherwise.
- **CLI default server is maincloud**: every call passes `--server local`.
- **Concurrent edits to `api/main.py`**: routers in separate files, lead wires them.

## 6. Size
L overall. Six tasks of at most M, three lanes in parallel on disjoint folders:
- Lane spacetime: **9a** module + bindings + owner-gated config + `test_room.sh` CLI path (M); **9b** bridge + `room_memory.py` + `room_ws.py` + memory branch of e2e (M).
- Lane frontend: **10a** scaffold, `RoomClient` types + ws impl, `/play`, `/board` skeleton, Playwright config + smoke (M); **10b** `/ops`, attack panel, QR, spacetime `RoomClient`, PushToTalk against `/rooms/{room}/stt` (M).
- Lane voice: **11** entire `backend/kernel/voice/`, routes, prerender, tests (M).

Run `invariant-reviewer` on 9b (worker gating, fail-closed outcome) and on the attacker snapshot stripping.

## Lead amendments
1. Engineers commit only their own paths (`git add <paths>`), never `git add -A`, never stash/reset/checkout other files. Several lanes run concurrently.
2. `api/main.py` wiring: each lane exposes an `APIRouter` in its own file; the lead adds `include_router`. Until then, lanes test their routers with their own small FastAPI app in tests.
3. Room REST/WS routes for memory mode (`/rooms/{room}/join`, `/snapshot`, `/ws` room snapshots) live in `backend/api/room_ws.py` owned by the spacetime lane; `/rooms/{room}/turns` and `/rooms/{room}/reset` live in the kernel lane (item 7) per docs/api.md. The spacetime lane's `room_ws.py` calls the SessionStore of item 7 through a small Protocol so it can be built before item 7 lands.
4. Frontend 10a must build and type-check with the kernel routes absent; the Playwright smoke is verified by the lead once items 7 and 9b land.
