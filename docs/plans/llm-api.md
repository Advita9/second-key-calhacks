# Plan: extractor, Margaret, Nessie, API (build-order 5 to 7)

Architect agent, 2026-10-23 22:55. Verified against installed `anthropic==2.3.0`: `Messages.parse` accepts `output_format`, `output_config` (`effort`), `system`, `timeout`, no `temperature`; `ParsedMessage.parsed_output` exists; `stop_reason` includes `"refusal"`. Lead amendments at the bottom override.

All paths under `backend/`.

## 1. Files

Item 5 (extractor)
- `kernel/llm/types.py` add `class ExtractorError(Exception)` only.
- `kernel/llm/heuristics.py` shared pure regex scanner used by MockExtractor and MockMargaret.
- `kernel/llm/schema.py` per-request output model via `create_model`, defensive `sanitize`.
- `kernel/llm/prompts.py` `EXTRACTOR_SYSTEM`, `render_evidence`.
- `kernel/llm/cache.py` disk cache under `backend/cache/llm/`.
- `kernel/llm/mock_extractor.py`, `kernel/llm/claude_extractor.py`, `kernel/llm/factory.py` (env selection).
- `tests/fixtures/llm/extractor_s03.json` recorded response; `tests/unit/test_heuristics.py`, `test_schema.py`, `test_mock_extractor.py`, `test_claude_extractor.py`, `test_cache.py`.

Item 6 (Margaret)
- `kernel/margaret/types.py`, `mock.py`, `claude.py`, `factory.py`; `fixtures/margaret.md` has fallback lines (eval-engineer wrote them).
- `tests/unit/test_margaret_mock.py`, `test_margaret_claude.py`, `tests/fixtures/llm/margaret_turn.json`; extend `tests/unit/test_boundary.py`.

Item 7a (rail + sessions)
- `kernel/nessie.py` `NessieClient`, `MockNessieTransport`, `NessieRail`, `RailError`.
- `kernel/rooms.py` `SessionStore`, `stage_for`, `draft_to_payment_in`, `public_outcome`.
- `tests/unit/test_nessie.py`, `test_rooms.py`.

Item 7b (HTTP)
- `api/settings.py`, `api/deps.py`, `api/schemas.py`, `api/hub.py` (WS fan-out), `api/routes/{payments,rooms,attack,audit,evalres,ws}.py`, `api/main.py` rewritten (routers, `Refusal` -> 409 handler, `/health`).
- `tests/api/test_flow.py`, `tests/api/test_attack.py`, `tests/api/test_ws.py`.

## 2. Interfaces

```python
# llm/heuristics.py
Kind = Literal["urgency","secrecy","authority","payment_method","new_relationship","threat","warmth"]
class Hit(BaseModel, frozen=True): kind: Kind; span: str; score: float
PATTERNS: dict[Kind, tuple[tuple[re.Pattern[str], float], ...]]   # e.g. secrecy r"do not tell (your )?(bank|daughter|family)" 0.9
def scan(text: str) -> tuple[Hit, ...]                             # case-insensitive, span = text[m.start():m.end()]

# llm/schema.py
def build_output_model(evidence_ids: Sequence[str]) -> type[BaseModel]   # Signal fields, source_id: Literal[*ids]; raises ExtractorError if empty
def sanitize(raw: Mapping[str, object], evidence: Sequence[EvidenceItem], *, max_signals: int = 12) -> ExtractorResult
# drops bad source_id / span not exact substring of that item's text / kind not in Signal kinds; clamps score to [0,1]; truncates to max_signals

# llm/cache.py
class ResponseCache:
    def __init__(self, root: Path, *, replay_only: bool)
    @staticmethod
    def key(model: str, system: str, messages: list[dict], schema: dict) -> str   # sha256 canonical json
    def get(self, k: str) -> dict | None;  def put(self, k: str, value: dict) -> None   # value = {"parsed": ..., "stop_reason": ...}

# llm/mock_extractor.py
class MockExtractor:
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult  # only caller/non-margaret speakers; never reads tags

# llm/claude_extractor.py
class ClaudeExtractor:
    def __init__(self, client: anthropic.Anthropic, *, model: str, cache: ResponseCache, max_tokens: int = 1024, max_signals: int = 12)
    def extract(self, conversation, payment) -> ExtractorResult         # any exception -> ExtractorError
def make_client(api_key: str) -> anthropic.Anthropic                  # Anthropic(api_key=..., timeout=7.0, max_retries=0)

# llm/factory.py
def build_extractor(env: Mapping[str, str]) -> tuple[Extractor, str]   # ("mock"|"real")

# margaret/types.py
class DraftPayment(BaseModel, frozen=True): amount_cents: PositiveInt; payee_name: str; rail: Rail
class MargaretTurn(BaseModel, frozen=True): reply: str; persuasion: float = Field(ge=0, le=1); draft_payment: DraftPayment | None = None
class Margaret(Protocol):
    def reply(self, history: Sequence[EvidenceItem], player_text: str, persuasion: float) -> MargaretTurn
SAFE_REPLY = "Let me think about that and call my daughter."
def update_persuasion(current: float, hits: Sequence[Hit]) -> float   # warmth +0.15, threat +0.15, authority +0.10, urgency/secrecy +0.05 each (max one per kind), clamp [0,1]
def extract_draft(history_text: str, persuasion: float) -> DraftPayment | None   # None unless persuasion > 0.75 and a $amount is present
class MockMargaret:  def __init__(self, persona_path: Path);  reply(...)
class ClaudeMargaret: def __init__(self, client, *, model, cache, persona_system: str); reply(...)  # output model MargaretOut{reply, persuasion: float, draft: DraftPayment|None}; failure -> MargaretTurn(SAFE_REPLY, persuasion, None)

# kernel/nessie.py
class NessieClient:
    def __init__(self, *, base_url: str, key: str, transport: httpx.BaseTransport | None = None, timeout: float = 15.0)
    def get_account(self, account_id: str) -> dict
    def withdraw(self, account_id: str, amount_dollars: int, description: str) -> str   # created id
    def deposit(self, account_id: str, amount_dollars: int, description: str) -> str
class MockNessieTransport(httpx.BaseTransport): seeded accounts {"acc_margaret": 2_400_000 cents}; 201 objectCreated wrapper; 404 unknown; 401 bad key
class NessieRail:   # implements rail.TransferRail
    def __init__(self, client: NessieClient, *, payee_accounts: Mapping[str, str])
    def submit(self, payment: Payment) -> str   # withdrawal(margaret) + deposit(payee or auto-created), description f"second-key {payment.id} {amount_cents}c"; raises RailError
def build_rail(env) -> tuple[NessieRail, str]

# kernel/rooms.py
class Room(BaseModel): id: str; history: list[EvidenceItem]; persuasion: float = 0.2; payment_id: str | None; balance_cents: int = 2_400_000; turn_count: int; ctx: AccountContext
class TurnResult(BaseModel, frozen=True): margaret_text: str; persuaded: bool; payment_id: str | None; stage: int; outcome: dict | None; evidence_id: str
class SessionStore:
    def __init__(self, kernel: Kernel, margaret: Margaret, *, default_ctx: AccountContext, evidence: Sequence[EvidenceItem] = ())
    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> TurnResult   # appends EV-{n:04d}, calls margaret, maybe kernel.create_payment(draft_to_payment_in(...), ctx, history+evidence)
    def reset(self, room_id: str) -> Room
def stage_for(persuaded: bool, payment: Payment | None) -> int   # 10/40/60(PENDING_REVIEW,DENIED)/70 HELD/90 ELIGIBLE/100 SUBMITTED
def draft_to_payment_in(d: DraftPayment, room: Room) -> PaymentIn   # account_ref = "ext_" + slug(payee_name); is_new = ref not in ctx.prior_payees
def public_outcome(decision: Decision | None, refusal: Refusal | None) -> dict   # {"decision", "refusal"}; no rule_ids

# api
Settings(demo_mode, mock_extractor, mock_margaret, anthropic_key, model, nessie_key, nessie_base_url, kernel_db, policy_path)  # from env via dotenv
deps: get_settings(), get_kernel() (lru_cache, one per process), get_sessions(), get_hub()
Hub: register(ws), unregister(ws), publish(event: dict)  # loop.call_soon_threadsafe from sync routes
Routes (all sync def): POST /payments, GET /payments/{id}, POST /payments/{id}/attest|certificate|release, POST /payments/{id}/mutate (404 unless demo_mode), POST /rooms/{id}/turns, POST /rooms/{id}/reset, POST /attack/inject|mutate|replay|self-approve, GET /audit, GET /audit/verify, POST /audit/tamper (404 unless demo), GET /eval/results (404 if eval/latest.json missing), GET /health, WS /ws
Refusal handler -> 409 {"refused": true, "invariant", "text"}
```

## 3. Tests first

- `test_schema.py`: foreign `source_id` rejected by the Literal model (I4); `sanitize` drops non-substring span, clamps 1.7 -> 1.0, caps at 12, never raises on garbage (I4).
- `test_mock_extractor.py`: S-03 text yields secrecy >= 0.7 and authority with real ids and exact spans; a conversation of only Margaret lines yields no signals; module imports no `tags` (I4).
- `test_claude_extractor.py` (fake client returning recorded fixture): happy path; `stop_reason="refusal"`/`"max_tokens"`; exception; `parsed_output=None`; parsed with foreign id -> each raises `ExtractorError`; `Kernel.create_payment` with a raising extractor -> HOLD, `X-00` (fail closed). Assert client constructed with `timeout=7.0, max_retries=0` and call kwargs lack `temperature`/`thinking`.
- `test_cache.py`: same request same key; `replay_only=True` miss -> `ExtractorError`; hit never calls client.
- `test_margaret_mock.py`: persuasion monotone under warmth, never exceeds 1; below 0.75 no draft; reply never contains digits >= 8 long (no account numbers); `ClaudeMargaret` with failing client -> `SAFE_REPLY`, persuasion unchanged, no draft.
- `test_boundary.py` extension: `kernel/state.py` and `kernel/service.py` import nothing from `kernel/margaret`; `MargaretTurn` has no field typed as `Event`/`Decision`/`State` (I4).
- `test_nessie.py`: `NessieRail.submit` via `MockNessieTransport` -> integer dollars, payment id in description, returns withdrawal id; 401 -> `RailError`; rail raising inside `release` -> payment not SUBMITTED (I1).
- `test_rooms.py`: `stage_for` table; draft over 0.75 creates a payment whose decision came from `decide` (new payee wire -> HELD, stage 70); `reset` restores persuasion/balance/history; `public_outcome` has no `rule_ids`.
- `tests/api/test_flow.py` (TestClient, `MOCK_EXTRACTOR=1 MOCK_MARGARET=1 DEMO_MODE=1 KERNEL_DB=:memory:`): A -> HOLD, `H-01` in rule_ids, >=1 signal with `source_id` in request ids (I4); B -> ALLOW -> cert -> release -> SUBMITTED with `nessie_transfer_id`; second release -> 409 `I3_REPLAY` (I3); C -> 409 `I5_CONFLICT` (I5); mutate after cert -> release 409 `I2_FINGERPRINT` (I2); CO_APPROVER on HELD stays HELD (I5/I6); `/audit/verify` ok then `/audit/tamper` -> `ok=false`, `first_bad_seq` set (I7); mutate/tamper return 404 when `DEMO_MODE=0`.
- `test_attack.py`: four routes return `refused: true` with `I2_FINGERPRINT`, `I3_REPLAY`, `I5_CONFLICT`; inject returns HOLD with `H-01` despite all-zero signals (I4).
- `test_ws.py`: `/ws` receives a `payment` event after `POST /payments` and an `attack` event after `/attack/replay`.

## 4. Mock boundary

- Extractor: `MOCK_EXTRACTOR=1` or empty `ANTHROPIC_API_KEY` -> `MockExtractor`. Else `ClaudeExtractor`; `DEMO_MODE=1` makes its cache `replay_only`. Model from `ANTHROPIC_MODEL`.
- Margaret: `MOCK_MARGARET=1` (add to `.env.example`) or no key -> `MockMargaret`.
- Nessie: `NESSIE_API_KEY` empty -> `NessieClient(transport=MockNessieTransport())`. Same client code, same rail either way.
- `/health.mode` reports `extractor`, `margaret`, `nessie` as `real|mock`; `tts`/`room` stay `mock`/`memory` until items 9 and 11.

## 5. Risks

- S-03 in fixtures/README has `ext_9f31` on the mule list, so D-01 fires and precedence gives DENY, not the HOLD scenario A requires. Mitigation: test_flow uses its own scenario A context with an empty mule list; fixtures task sets S-03 expected to DENY.
- `effort: low` plus `output_format` may be rejected at runtime for this model. Mitigation: pass `output_config` only when `ANTHROPIC_EFFORT` is set; default omit.
- DEMO_MODE replay with a cold cache turns Bay Roofing into HELD. Mitigation: `scripts/demo.py` (item 12) warms the cache or runs `MOCK_EXTRACTOR=1`; document in MORNING.md.
- Mock persuasion too slow or too fast for a 2-minute demo. Mitigation: weights in one table, unit test asserts 3 warm+fear turns cross 0.75.
- 7s extractor inside the kernel `RLock` blocks all routes. Mitigation: sync routes run in FastAPI's threadpool; one room per process is fine tonight; note in DECISIONS.
- `lru_cache` kernel singleton leaks across tests. Mitigation: `deps.reset()` called from a conftest autouse fixture.
- Nessie payee accounts do not exist in the sandbox. Mitigation: `NessieRail` lazily creates a customer+account per `account_ref` and caches the map in `backend/cache/nessie_payees.json`.

## 6. Size

L. Split into four tasks of at most M: **T5** extractor (M), **T6** Margaret (S), **T7a** nessie + rooms (M), **T7b** API routes, WS, test_flow (M). `invariant-reviewer` after T5 and T7b at minimum. Commits: "extractor: mock, claude, cache", "margaret persona", "nessie rail and room sessions", "api routes per docs/api.md".

## Lead amendments
1. Scenario A in `tests/api/test_flow.py` uses its own AccountContext with an empty mule list so the expected outcome is HOLD with H-01 (plus H-02/H-03 may fire). Fixture S-03 keeps `ext_9f31` on the mule list with expected DENY.
2. The extractor's real-API call runs OUTSIDE the kernel RLock: `Kernel.create_payment` calls the extractor before taking the lock (the extractor is pure with respect to kernel state; its output is just data). Document in code.
3. Rooms: the `/rooms/{room}/turns` route also accepts multipart (audio + optional text) later for push-to-talk; design the handler so JSON and multipart both work (item 11 adds STT).
4. `MockMargaret` must produce, within 3 to 4 attacker turns that combine warmth plus fear or authority, persuasion > 0.75 and a draft, so a live demo reaches stage 60/70 quickly. Pure urgency alone should take 6+ turns.
5. T5 and T6 can run in parallel (disjoint folders `kernel/llm/` and `kernel/margaret/`) after Task B of the kernel foundation lands. T7a and T7b sequential after both.
