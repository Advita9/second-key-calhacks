# Plan: kernel foundation (build-order 0 to 3)

Written by the architect agent, 2026-10-23 22:20. Lead amendments at the bottom override anything above them.

Toolchain note: `uv` is installed, Python 3.12 is not (system is 3.14). Scaffold must pin `requires-python = ">=3.12,<3.13"` with `.python-version` = 3.12 so uv downloads it on first `uv sync`.

## 1. Files

Scaffold (item 0)
- `backend/pyproject.toml` uv project, deps: fastapi, uvicorn[standard], pydantic>=2, pyyaml, anthropic, httpx, python-dotenv, hypothesis, pytest, pytest-asyncio, ruff, mypy, types-PyYAML. `[tool.pytest.ini_options] pythonpath=["."]`, ruff + mypy strict.
- `backend/.python-version` `3.12`
- `backend/kernel/__init__.py`, `backend/api/__init__.py`, `backend/api/main.py` (only `/health` for now).
- `backend/tests/conftest.py` registers Hypothesis profiles `dev`(200) `ci`(2000, deadline=None), loads via `HYPOTHESIS_PROFILE`; fixtures `clock`, `kernel` (`:memory:`).
- `backend/tests/{unit,property,api,voice,redteam}/__init__.py` plus one smoke test each so the acceptance script does not fail on empty dirs.
- `spacetime/package.json` (`build` = `tsc --noEmit`), `bridge/package.json`, `frontend/.gitkeep`, `fixtures/cases/.gitkeep`, `scripts/dev.sh` (`uv sync`, starts uvicorn).

Domain (item 1)
- `kernel/models.py` Pydantic frozen models and enums.
- `kernel/fingerprint.py` canonical JSON + sha256.
- `kernel/state.py` transition table, `transition()` chokepoint, `IllegalTransition`.
- `kernel/audit.py` hash-chained log over SQLite, `verify`, `tamper` (DEMO only).
- `kernel/db.py` `connect(path)`, `SCHEMA` DDL, `BEGIN IMMEDIATE` helper.
- `kernel/clock.py` `Clock` Protocol, `SystemClock`, `FakeClock`.

Policy (item 2)
- `kernel/policy/expr.py` tokenizer, recursive-descent parser, evaluator, `free_identifiers`.
- `kernel/policy/env.py` `KNOWN_IDENTIFIERS` frozenset, `build_env()`.
- `kernel/policy/engine.py` `load_policy`, `decide`, `fail_closed`.
- `kernel/policy/v1.yaml` exactly the shape in docs/api.md (plus lead amendment rules below).

Certificates and facade (item 3)
- `kernel/certs.py` issue/verify/consume SQL.
- `kernel/attest.py` capability rules, I5 conflict check.
- `kernel/llm/types.py` `Signal`, `ExtractorResult`, `EvidenceItem`, `Extractor` Protocol, `NullExtractor`.
- `kernel/rail.py` `TransferRail` Protocol, `NullTransferRail`.
- `kernel/service.py` `Kernel` facade and `Cmd` trace types.

## 2. Interfaces

```python
# models.py
class Rail(StrEnum): WIRE ACH ZELLE CARD CRYPTO
class State(StrEnum): DRAFT PENDING_REVIEW HELD ELIGIBLE_TO_SUBMIT SUBMITTED DENIED CANCELLED
class Outcome(StrEnum): ALLOW HOLD DENY
class Capability(StrEnum): CUSTOMER_CHECKIN CO_APPROVER BANK_REVIEW
class Invariant(StrEnum): I1_NO_CERT I1_NOT_ELIGIBLE I2_FINGERPRINT I3_REPLAY I3_EXPIRED I5_CONFLICT I6_DENIED
class Beneficiary(BaseModel, frozen=True): name: str; account_ref: str; is_new: bool
class PaymentIn(BaseModel, frozen=True): account_id: str; amount_cents: PositiveInt; currency: str="USD"; beneficiary: Beneficiary; rail: Rail; conversation_id: str
class Payment(PaymentIn, frozen=True): id: str; state: State; fingerprint: str; policy_version: str; created_at: datetime; nessie_transfer_id: str|None=None
class AccountContext(BaseModel, frozen=True): baseline_90d_cents: int; known_billers: list[str]; prior_payees: list[str]; mule_list: list[str]; known_biller_cap_cents: int=1_500_000
class Attestation(BaseModel, frozen=True): id: str; payment_id: str; actor_id: str; capability: Capability; fingerprint: str; note: str|None; created_at: datetime; voided_at: datetime|None
class Certificate(BaseModel, frozen=True): id: str; payment_id: str; fingerprint: str; policy_version: str; actor_id: str; capability: Capability; nonce: str; issued_at: datetime; expires_at: datetime; consumed_at: datetime|None; voided_at: datetime|None
class Decision(BaseModel, frozen=True): outcome: Outcome; rule_ids: tuple[str, ...]; policy_version: str
class Refusal(Exception): invariant: Invariant; @property text -> f"SETTLEMENT REFUSED · {invariant}"

# fingerprint.py
def fingerprint(p: PaymentIn, policy_version: str) -> str  # sha256(json.dumps({account_id,amount_cents,currency,beneficiary_account_ref,rail,policy_version}, sort_keys=True, separators=(",",":")))

# state.py   (only place that writes Payment.state)
class Submitted(Event); class Decided(Event): outcome: Outcome; rule_ids: tuple[str,...]
class HoldLifted(Event); class Released(Event): certificate_id: str; transfer_id: str
class Mutated(Event): new_fingerprint: str; class Cancelled(Event)
TRANSITIONS: dict[tuple[State, type[Event]], State]   # DENIED and SUBMITTED have no outgoing rows
def transition(p: Payment, ev: Event, *, audit: AuditLog, actor: str) -> Payment  # raises IllegalTransition

# audit.py   table audit(seq INTEGER PRIMARY KEY, ts TEXT, actor TEXT, kind TEXT, payload TEXT, prev_hash TEXT, hash TEXT)
def chain_hash(seq:int, ts:str, actor:str, kind:str, payload_json:str, prev_hash:str) -> str
class AuditLog: append(actor, kind, payload: dict) -> AuditEvent; verify() -> VerifyResult(ok, length, first_bad_seq); tamper(seq, patch) -> None; tail(limit) -> list[AuditEvent]

# clock.py
class Clock(Protocol): def now(self) -> datetime
class FakeClock: advance(seconds: float) -> None

# policy/expr.py
def tokenize(src: str) -> list[Token]; def parse(src: str) -> Node; def evaluate(node: Node, env: Mapping[str, object]) -> object
def free_identifiers(node: Node) -> frozenset[str]
class ParseError(ValueError); class EvalError(ValueError)
# grammar: or > and > not > cmp(== != < <= > >= in, not in) > sum(+ -) > prod(* /) > unary(-) > atom(NUMBER STRING true false IDENT(.IDENT)* [list] (expr))
# ALL_CAPS bare IDENT is a string literal; others must be in env. depth cap 64, token cap 512.

# policy/engine.py
class Rule(BaseModel, frozen=True): id: str; when: str; outcome: Outcome
class Policy(BaseModel, frozen=True): version: str; rules: tuple[Rule,...]; default: Outcome; precedence: tuple[Outcome,Outcome,Outcome]; compiled: dict[str, Node]
def load_policy(path: Path) -> Policy      # raises PolicyLoadError: missing id/when/outcome, dup id, bad outcome, parse error, identifier not in KNOWN_IDENTIFIERS, default == ALLOW, precedence not a permutation
def decide(p: PaymentIn, signals: Sequence[Signal], ctx: AccountContext, policy: Policy) -> Decision  # EvalError on any rule -> HOLD + "X-01"
def fail_closed(d: Decision, rule_id: str) -> Decision  # outcome = max(HOLD, d.outcome)

# llm/types.py   (nothing here imports state.py; test enforces)
class Signal(BaseModel, frozen=True): kind: Literal[...]; score: float(0..1); source_id: str; evidence_span: str
class ExtractorResult(BaseModel, frozen=True): signals: tuple[Signal,...]; summary: str
class Extractor(Protocol): def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult
class NullExtractor: returns ExtractorResult(signals=(), summary="")

# service.py
class Kernel:
    def __init__(self, db_path: str=":memory:", *, policy: Policy, clock: Clock=SystemClock(), extractor: Extractor=NullExtractor(), rail: TransferRail=NullTransferRail(), cert_ttl_s: int=120, extractor_timeout_s: float=8.0)
    def create_payment(self, p: PaymentIn, ctx: AccountContext, conversation: Sequence[EvidenceItem]=()) -> tuple[Payment, Decision]
    def attest(self, payment_id: str, actor_id: str, capability: Capability, note: str|None=None) -> Payment
    def issue_certificate(self, payment_id: str, actor_id: str, capability: Capability) -> Certificate
    def release(self, payment_id: str, certificate_id: str, nonce: str) -> Payment
    def mutate(self, payment_id: str, patch: dict, ctx: AccountContext) -> tuple[Payment, Decision]
    def get(self, payment_id: str) -> PaymentRecord   # payment + attestations + certificates + history
    def audit_verify(self) -> VerifyResult
    def apply(self, cmd: Cmd) -> CmdResult            # never raises; for traces
Cmd = Create | Attest | IssueCert | Release | Mutate | Tick   # frozen dataclasses mirroring the method args; Tick(seconds) advances FakeClock
CmdResult(ok: bool, invariant: Invariant|None, payment: Payment|None, certificate: Certificate|None)
```

Semantics the engineer must follow:
- `create_payment`: insert DRAFT, `transition(Submitted)`, run extractor in try/except with timeout (any failure -> `fail_closed(d,"X-00")`), `decide`, `transition(Decided)`: ALLOW->ELIGIBLE_TO_SUBMIT, HOLD->HELD, DENY->DENIED. The only call site that turns `Decision` into an `Event`.
- `attest`: DENIED/SUBMITTED -> `Refusal(I6_DENIED)` / `I1_NOT_ELIGIBLE`. CO_APPROVER with `actor_id == beneficiary.account_ref` -> `I5_CONFLICT` (compare refs, never names). BANK_REVIEW on HELD -> `transition(HoldLifted)`. CO_APPROVER and CUSTOMER_CHECKIN only insert an attestation row.
- `issue_certificate`: state must be ELIGIBLE_TO_SUBMIT else `I1_NOT_ELIGIBLE` (DENIED -> `I6_DENIED`). BANK_REVIEW only; CO_APPROVER or CUSTOMER_CHECKIN -> `I1_NOT_ELIGIBLE` with audit kind `CERT_REFUSED_CAPABILITY`. nonce = `secrets.token_hex(16)`, expires = now + ttl.
- `release` check order: payment DENIED -> I6; cert missing or wrong payment -> I1_NO_CERT; `voided_at` or `cert.fingerprint != payment.fingerprint` -> I2; `consumed_at` -> I3_REPLAY; `expires_at <= now` -> I3_EXPIRED; nonce mismatch -> I1_NO_CERT; state != ELIGIBLE -> I1_NOT_ELIGIBLE. Then inside `BEGIN IMMEDIATE`: `UPDATE certificate SET consumed_at=? WHERE id=? AND consumed_at IS NULL AND voided_at IS NULL AND fingerprint=?`; `rowcount != 1` -> I3_REPLAY; call `rail.submit`, `transition(Released)`, commit. `Kernel` also holds a `threading.RLock` across every public method; SQLite opened `check_same_thread=False`.
- `mutate`: DENIED -> I6; SUBMITTED -> I1_NOT_ELIGIBLE. Apply patch to PaymentIn, recompute fingerprint, `UPDATE ... SET voided_at` on all attestations and certificates, `transition(Mutated)` -> PENDING_REVIEW, then re-run extractor+decide as in create.
- Every refusal appends an audit event `REFUSED` with the invariant before raising.

## 3. Tests first (backend/tests/unit)

- `test_fingerprint.py`: same input same hash; each of the six fields changes it; name change does not (I2).
- `test_state.py`: every legal edge; DENIED and SUBMITTED have no outgoing edges (I6, I1); `transition` is the only writer (grep `backend/kernel` for `"state"` / `.state =` outside state.py).
- `test_audit.py`: append N, verify ok; `tamper(seq)` -> `ok=False, first_bad_seq=seq`; re-linking prev_hash on a later row still detected (I7).
- `test_expr.py`: one test per operator and precedence case; ALL_CAPS literal; unknown identifier raises; depth bomb `((((...` raises ParseError; `/0` raises EvalError; fuzz with Hypothesis text never raises anything but ParseError/EvalError and no `eval` in source (grep).
- `test_engine.py`: load v1.yaml ok; fixtures with missing outcome, unknown identifier, `default: ALLOW` each raise at load; precedence DENY>HOLD>ALLOW when several fire; no rule fires -> HOLD; EvalError -> HOLD + X-01; `fail_closed` never lowers (I4 fail-closed).
- `test_boundary.py`: `kernel/llm/*` imports nothing from `state`/`service`; `state.py` imports nothing from `llm`; `Decided` cannot be built from `ExtractorResult` (I4).
- `test_certs.py`: happy path ELIGIBLE->cert->release->SUBMITTED; release twice -> I3_REPLAY; `clock.advance(121)` -> I3_EXPIRED; wrong nonce -> I1_NO_CERT; cert from other payment -> I1_NO_CERT; two threads on a barrier releasing same cert -> exactly one SUBMITTED (I1, I3).
- `test_mutate.py`: after cert issued, mutate amount -> fingerprint changes, all attestations/certs voided, release -> I2_FINGERPRINT (I2).
- `test_attest.py`: CO_APPROVER whose actor_id equals beneficiary.account_ref -> I5_CONFLICT even with a different name; CO_APPROVER on HELD stays HELD; CO_APPROVER cannot issue cert; BANK_REVIEW lifts HELD; any actor on DENIED -> I6_DENIED (I5, I6).
- `test_service_apply.py`: `apply` never raises for a random Cmd; ok=False carries invariant (smoke for item 4).

## 4. Mock boundary

Everything in items 0 to 3 runs with no keys. `NullExtractor` and `NullTransferRail` are defaults; `/health` reports `mode.extractor="mock"`. Switch points reserved: `MOCK_EXTRACTOR=1`/`ANTHROPIC_API_KEY` (item 5), `NESSIE_API_KEY` (item 7), `DEMO_MODE=1` gates `mutate` and `audit.tamper` at the API layer only; the kernel methods exist regardless so tests can call them.

## 5. Risks

- Python 3.12 absent: uv downloads it on `uv sync` because of `.python-version`; if download fails, lower pin to `>=3.12` and record in DECISIONS.
- Bare enum words (`WIRE`) in `when`: ALL_CAPS literal rule, documented and tested.
- SQLite `:memory:` with threads: one shared connection under the `RLock`; never open per-thread connections to `:memory:`.
- Hypothesis 2000 examples slow with SQLite: keep `Kernel` setup under 5 ms (`PRAGMA journal_mode=MEMORY`, DDL once).
- Refusal ordering leaks info: fixed order above; attacker-facing routes later return only `invariant`.
- Datetime stringification in audit payloads breaks hashing: canonical JSON with `default=str`, `sort_keys=True`.

## 6. Size

L. Split:
- Task A (M): items 0, 1, 2 (scaffold, models, fingerprint, state, audit, expr, engine, v1.yaml). Commit "kernel domain and policy engine".
- Task B (M): item 3 (`llm/types.py`, `certs.py`, `attest.py`, `rail.py`, `service.py`, `apply`). Commit "certificates and release verifier". Run `invariant-reviewer` after each.

## Lead amendments (override the above)

1. `known_biller_cap_cents` default is 1_500_000 ($15,000), and the fixtures carry it in `account_context`.
2. `beneficiary.is_known_biller` (policy env) is true when `beneficiary.name` is in `ctx.known_billers` OR `beneficiary.account_ref` is in `ctx.prior_payees`. `beneficiary.on_mule_list` is true when `beneficiary.account_ref` is in `ctx.mule_list` (account_ref only, never name; names can be spoofed with homoglyphs).
3. `v1.yaml` contains the five rules in docs/api.md PLUS three signal rules the fixtures assume: `H-04: signals.urgency >= 0.8 and beneficiary.is_new -> HOLD`, `H-05: signals.authority >= 0.7 and signals.payment_method >= 0.5 -> HOLD`, `H-06: signals.threat >= 0.7 -> HOLD`. `signals.<kind>` in the env is the MAX score of valid signals of that kind, 0.0 if none.
4. Policy env identifiers (KNOWN_IDENTIFIERS): `amount_cents, currency, rail, baseline_90d_cents, known_biller_cap_cents, beneficiary.is_new, beneficiary.is_known_biller, beneficiary.on_mule_list, signals.urgency, signals.secrecy, signals.authority, signals.payment_method, signals.new_relationship, signals.threat, signals.count`.
5. The rule precedence in `decide`: collect all rules whose `when` is true; outcome = the highest-precedence outcome among them (DENY > HOLD > ALLOW); `rule_ids` = ids of every rule that fired, in YAML order. If none fired, outcome = default (HOLD) and rule_ids = ("DEFAULT",).
6. Items 0 to 3 land as two commits as the architect split them, each followed by `invariant-reviewer`.
