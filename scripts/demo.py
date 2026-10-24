#!/usr/bin/env python3
"""Second Key demo: scenarios A, B, C, the attack panel and the audit chain, end to end.

Builds the FastAPI app in-process (`fastapi.testclient.TestClient`, no port, no network) and
drives it the way the board, the bridge and the ops console do. Prints one line per step with
timing and a scoreboard at the end. Exit 1 if any step's expectation fails.

Usage (either cwd works):
    cd backend && DEMO_MODE=1 uv run python ../scripts/demo.py          # mocks, offline
    uv run --project backend python scripts/demo.py --real              # .env, fills the cache
    cd backend && DEMO_MODE=1 uv run python ../scripts/demo.py --real   # .env, replay only
    uv run --project backend python scripts/demo.py --warm              # fill every demo prompt

Flags:
    --real   load `.env`; real extractor and Margaret through the disk cache in backend/cache/llm.
             Without DEMO_MODE=1 the first run warms the cache; with DEMO_MODE=1 it replays and a
             cache miss fails closed (HOLD / safe reply) instead of calling the network.
    --warm   like --real but misses always fill the cache, and S-03, L-01 and L-40 are also run
             through the extractor so every demo prompt is on disk.
    --json   print the scoreboard as JSON on the last line.

Env defaults set when absent: KERNEL_DB=:memory:, ROOM_BACKEND=memory, TTS_PROVIDER=mock,
STT_PROVIDER=mock, NESSIE_API_KEY="" (mock rail), KERNEL_LOAD_DOTENV=0 unless --real/--warm.
DEMO_MODE is always on inside the app (the audit tamper and mutate routes need it). Whether the
LLM cache is replay-only is decided here: `--real` with DEMO_MODE=1 in the caller's env and no
`--warm` sets LLM_CACHE_MODE=replay; otherwise auto. MOCK_EXTRACTOR and MOCK_MARGARET are
honoured as set by the caller. X-Ops-Token (OPS_TOKEN from .env or the process env) is sent on
every request.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CASES = REPO_ROOT / "fixtures" / "cases"
ROOM = "DEMO"
PLAYER_HANDLE = "judge1"
OPS_ACTOR = "ops_demo"
_TRUE = {"1", "true", "yes", "on"}

# Scenario A: the IRS/warmth script, shared with POST /rooms/{room}/scripted-attack through
# fixtures/demo_script.json (`turns`, `followup`). MockMargaret drafts $1,850 WIRE to
# "Agent Daniels" on the third line; the follow-up is only sent when a persona has not drafted
# after the three turns.
DEMO_SCRIPT = REPO_ROOT / "fixtures" / "demo_script.json"


def load_script() -> tuple[tuple[str, ...], str]:
    raw = json.loads(DEMO_SCRIPT.read_text("utf-8"))
    turns = tuple(str(t) for t in raw["turns"])
    followup = str(raw["followup"])
    if not turns or not followup:
        raise ValueError(f"{DEMO_SCRIPT}: needs non-empty 'turns' and 'followup'")
    return turns, followup


SCENARIO_A_SCRIPT, SCENARIO_A_FOLLOWUP = load_script()

EXPECTED_ATTACKS: tuple[tuple[str, str], ...] = (
    ("inject", "POLICY_HOLD"),
    ("mutate", "I2_FINGERPRINT"),
    ("replay", "I3_REPLAY"),
    ("self-approve", "I5_CONFLICT"),
)


class StepFailed(Exception):
    """An expectation in a demo step did not hold."""


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def expect(cond: bool, message: str) -> None:
    if not cond:
        raise StepFailed(message)


def load_case(case_id: str) -> dict[str, Any]:
    raw = json.loads((CASES / f"{case_id}.json").read_text("utf-8"))
    assert isinstance(raw, dict)
    return raw


def case_body(case_id: str, conversation_id: str, **ctx_over: Any) -> dict[str, Any]:
    """`POST /payments` body from a fixture: payment, transcript and account context."""
    c = load_case(case_id)
    return {
        **c["payment"],
        "conversation_id": conversation_id,
        "conversation": c["conversation"],
        "account_context": {**c["account_context"], **ctx_over},
    }


# ---------------------------------------------------------------- environment


@contextmanager
def demo_env(*, real: bool, warm: bool) -> Iterator[dict[str, str]]:
    """Set the process env for the run and restore it afterwards (tests import `run`)."""
    demo_requested = truthy(os.environ.get("DEMO_MODE"))
    replay_only = demo_requested and not warm
    wanted: dict[str, str] = {
        "KERNEL_DB": ":memory:",
        "ROOM_BACKEND": "memory",
        "TTS_PROVIDER": "mock",
        "STT_PROVIDER": "mock",
        "NESSIE_API_KEY": "",  # mock rail: the demo never moves sandbox money
        "KERNEL_LOAD_DOTENV": "1" if (real or warm) else "0",
    }
    if real or warm:
        wanted.setdefault("MOCK_EXTRACTOR", "0")
        wanted.setdefault("MOCK_MARGARET", "0")
    forced: dict[str, str] = {
        "DEMO_MODE": "1",  # tamper and mutate routes
        # The offline guarantee lives here, not in DEMO_MODE: --real without --warm replays
        # the disk cache only; --warm (or no DEMO_MODE) may call the network and fill it.
        "LLM_CACHE_MODE": "replay" if replay_only else "auto",
        "LLM_CACHE_WARM": "0" if replay_only else "1",  # legacy alias, kept in step
    }
    saved = {k: os.environ.get(k) for k in [*wanted, *forced]}
    try:
        for k, v in wanted.items():
            os.environ.setdefault(k, v)
        os.environ.update(forced)
        yield {"replay_only": "1" if replay_only else "0", "real": "1" if (real or warm) else "0"}
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


# ---------------------------------------------------------------- runner


class Demo:
    def __init__(self, client: Any, out: TextIO, ops_token: str, *, real: bool = False) -> None:
        self.client = client
        self.out = out
        self.real = real
        self.ops_headers = {"X-Ops-Token": ops_token} if ops_token else {}
        # Every route that can need the operator token gets it (attest as BANK_REVIEW,
        # certificate, release, mutate, deny, attack/*, audit/tamper, rooms reset, and
        # POST /payments with a caller-supplied context). Routes that do not need it ignore it.
        if ops_token:
            self.client.headers.update(self.ops_headers)
        self.failures: list[str] = []
        self.facts: dict[str, Any] = {
            "scenario_a_payment_id": None,
            "scenario_b_payment_id": None,
            "scenario_c_payment_id": None,
            "scam_payment_ids": [],
            "attacks_refused": 0,
            "tamper_detected": False,
            "modes": {},
            "health_cache": {},
        }

    # -- plumbing -----------------------------------------------------------

    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    def step(self, number: int, title: str, fn: Callable[[], str]) -> None:
        t0 = time.perf_counter()
        try:
            summary = fn()
            status = "ok"
        except StepFailed as e:
            summary, status = str(e), "FAIL"
            self.failures.append(f"step {number} {title}: {e}")
        except Exception as e:  # noqa: BLE001  the report must finish
            summary, status = f"{type(e).__name__}: {e}", "FAIL"
            self.failures.append(f"step {number} {title}: {type(e).__name__}: {e}")
        dt = time.perf_counter() - t0
        self.say(f"[{number}] {status:<4} {dt:6.2f}s  {title}: {summary}")

    def post(self, path: str, body: dict[str, Any] | None = None, *, ops: bool = False) -> Any:
        headers = self.ops_headers if ops else {}
        return self.client.post(path, json=body, headers=headers)

    def get(self, path: str) -> Any:
        return self.client.get(path)

    # -- steps --------------------------------------------------------------

    def step_health(self) -> str:
        r = self.get("/health")
        expect(r.status_code == 200, f"/health {r.status_code}")
        body = r.json()
        expect(body.get("ok") is True, "health.ok is not true")
        modes = body.get("mode", {})
        self.facts["modes"] = modes
        self.facts["health_cache"] = body.get("cache", {})
        mode_s = " ".join(f"{k}={v}" for k, v in modes.items())
        cache_s = " ".join(f"{k}={v}" for k, v in body.get("cache", {}).items())
        return f"policy={body.get('policy_version')} {mode_s} cache[{cache_s}]"

    def step_scenario_a(self) -> str:
        j = self.post(f"/rooms/{ROOM}/join", {"handle": PLAYER_HANDLE})
        expect(j.status_code == 200, f"join {j.status_code}: {j.text[:120]}")
        player_id = str(j.json()["player_id"])
        self.say(f"    {PLAYER_HANDLE} joined room {ROOM} as {player_id}")
        last: dict[str, Any] | None = None
        lines = list(SCENARIO_A_SCRIPT)
        for i, text in enumerate(lines, start=1):
            r = self.post(
                f"/rooms/{ROOM}/turns",
                {"turn_id": f"demo-{i}", "player_id": player_id, "text": text},
            )
            expect(r.status_code == 200, f"turn {i} {r.status_code}: {r.text[:120]}")
            last = r.json()
            self.say(f"    {PLAYER_HANDLE}: {text}")
            self.say(
                f"    Margaret: {last['margaret_text']}  "
                f"[persuaded={last['persuaded']} stage={last['stage']}]"
            )
            if last.get("payment_id"):
                break
            if i == len(lines) and len(lines) == len(SCENARIO_A_SCRIPT):
                lines.append(SCENARIO_A_FOLLOWUP)  # one more try for a real persona
        assert last is not None
        pid = last.get("payment_id")
        if not pid:
            # The mock must draft (acceptance path). The real persona may resist the script;
            # that is a persona outcome, not a kernel failure, and nothing was released.
            expect(self.real, f"Margaret never drafted a payment in {len(lines)} turns")
            expect(last["stage"] in {10, 40}, f"no payment but stage {last['stage']}")
            return (
                f"RESISTED: real Margaret gave no draft after {len(lines)} turns "
                f"(stage={last['stage']}); kernel not exercised in this scenario"
            )
        outcome = last.get("outcome") or {}
        decision = outcome.get("decision")
        rule_ids = list(outcome.get("rule_ids") or [])
        expect(decision in {"HOLD", "DENY"}, f"decision {decision!r}, expected HOLD or DENY")
        expect(bool(rule_ids), "no rule ids on the decision")
        expect(last["stage"] in {60, 70}, f"stage {last['stage']}, expected 60 or 70")
        rec = self.get(f"/payments/{pid}").json()
        expect(rec["state"] in {"HELD", "DENIED"}, f"state {rec['state']}")
        signals = (rec.get("decision") or {}).get("signals") or []
        cited = sorted({s["source_id"] for s in signals})
        self.facts["scenario_a_payment_id"] = pid
        self.facts["scam_payment_ids"].append(pid)
        return (
            f"payment {pid} {rec['beneficiary']['name']} {rec['amount_cents']} cents "
            f"{rec['rail']} -> {decision} {' '.join(rule_ids)} state={rec['state']} "
            f"stage={last['stage']} signals={len(signals)} citing {','.join(cited) or '-'}"
        )

    def step_scenario_b(self) -> str:
        r = self.post("/payments", case_body("L-01", "demo_b"))
        expect(r.status_code == 200, f"create {r.status_code}: {r.text[:120]}")
        p = r.json()
        pid = p["id"]
        self.facts["scenario_b_payment_id"] = pid
        outcome = p["decision"]["outcome"]
        rules = p["decision"]["rule_ids"]
        expect(outcome == "ALLOW", f"decision {outcome} {rules}, expected ALLOW")
        expect(p["state"] == "ELIGIBLE_TO_SUBMIT", f"state {p['state']}")
        c = self.post(
            f"/payments/{pid}/certificate",
            {"actor_id": OPS_ACTOR, "capability": "BANK_REVIEW"},
            ops=True,
        )
        expect(c.status_code == 200, f"certificate {c.status_code}: {c.text[:120]}")
        cert = c.json()["certificate"]
        expect(cert["fingerprint"] == p["fingerprint"], "certificate fingerprint mismatch")
        rel = self.post(
            f"/payments/{pid}/release",
            {"certificate_id": cert["id"], "nonce": cert["nonce"]},
            ops=True,
        )
        expect(rel.status_code == 200, f"release {rel.status_code}: {rel.text[:120]}")
        released = rel.json()
        expect(released["state"] == "SUBMITTED", f"state after release {released['state']}")
        expect(bool(released.get("nessie_transfer_id")), "no nessie_transfer_id")
        return (
            f"payment {pid} Bay Roofing 800000 cents ACH baseline 300000 -> ALLOW "
            f"{' '.join(rules)} -> certificate {cert['id']} (BANK_REVIEW, expires "
            f"{cert['expires_at'][11:19]}Z) -> release -> SUBMITTED "
            f"nessie_transfer_id={released['nessie_transfer_id']}"
        )

    def step_scenario_c(self) -> str:
        r = self.post("/payments", case_body("L-40", "demo_c"))
        expect(r.status_code == 200, f"create {r.status_code}: {r.text[:120]}")
        p = r.json()
        pid = p["id"]
        self.facts["scenario_c_payment_id"] = pid
        outcome = p["decision"]["outcome"]
        rules = p["decision"]["rule_ids"]
        expect(outcome in {"HOLD", "DENY"}, f"decision {outcome}, expected HOLD")
        a = self.post(
            f"/payments/{pid}/attest",
            {"actor_id": "ext_priya", "capability": "CO_APPROVER", "note": "looks fine"},
            ops=True,
        )
        expect(a.status_code == 409, f"attest {a.status_code}: {a.text[:120]}")
        body = a.json()
        expect(body.get("refused") is True, "attest not refused")
        expect(body.get("invariant") == "I5_CONFLICT", f"invariant {body.get('invariant')}")
        rec = self.get(f"/payments/{pid}").json()
        expect(rec["attestations"] == [], "an attestation was recorded")
        return (
            f"payment {pid} Priya Shah 900000 cents ZELLE -> {outcome} {' '.join(rules)}; "
            f"Priya attests as CO_APPROVER -> 409 {body['invariant']} ({body.get('text')}); "
            f"state={rec['state']} attestations=0"
        )

    def step_attacks(self) -> str:
        refused = 0
        parts: list[str] = []
        for name, want in EXPECTED_ATTACKS:
            r = self.post(f"/attack/{name}")
            is_json = r.headers.get("content-type", "").startswith("application/json")
            body = r.json() if is_json else {}
            inv = body.get("invariant")
            ok = r.status_code == 200 and body.get("refused") is True and inv == want
            if ok:
                refused += 1
            # Print the kernel's own refusal text only (the self-approve attack says
            # ATTESTATION REFUSED, the others SETTLEMENT REFUSED); never a second prefix.
            text = body.get("text") or f"HTTP {r.status_code}"
            n_steps = len(body.get("steps") or [])
            self.say(f"    /attack/{name:<13} {text}  ({n_steps} steps; {inv or 'NOT REFUSED'})")
            parts.append(f"{name}={'refused' if ok else 'NOT REFUSED'}")
            if not ok:
                self.failures.append(
                    f"attack {name}: status {r.status_code} refused={body.get('refused')} "
                    f"invariant={inv} (expected {want})"
                )
        self.facts["attacks_refused"] = refused
        expect(refused == len(EXPECTED_ATTACKS), f"{refused}/{len(EXPECTED_ATTACKS)} refused")
        return f"{refused}/{len(EXPECTED_ATTACKS)} refused: {' '.join(parts)}"

    def step_audit(self) -> str:
        v1 = self.get("/audit/verify").json()
        expect(v1.get("ok") is True, f"verify before tamper: {v1}")
        t = self.post("/audit/tamper", ops=True)
        expect(t.status_code == 200, f"tamper {t.status_code}: {t.text[:120]}")
        seq = t.json()["tampered_seq"]
        v2 = self.get("/audit/verify").json()
        expect(v2.get("ok") is False, "verify after tamper still ok")
        expect(v2.get("first_bad_seq") == seq, f"first_bad_seq {v2.get('first_bad_seq')} != {seq}")
        self.facts["tamper_detected"] = True
        return (
            f"verify ok length={v1.get('length')}; tamper seq {seq}; "
            f"verify ok=false first_bad_seq={v2.get('first_bad_seq')}"
        )

    def step_warm_extras(self) -> str:
        """--warm only: push S-03, L-01 and L-40 through the extractor so eval and the API
        tests' scenario bodies are cached too (L-01 and L-40 are usually hits already)."""
        from kernel.llm.cache import ResponseCache

        before = ResponseCache.totals()
        done: list[str] = []
        warm_cases: tuple[tuple[str, dict[str, Any]], ...] = (
            ("S-03", {"mule_list": []}),  # the API tests' scenario A body (HOLD H-01)
            ("S-03", {}),  # fixture context (DENY D-01); same prompt, a cache hit
            ("L-01", {}),
            ("L-40", {}),
        )
        for cid, ctx_over in warm_cases:
            r = self.post("/payments", case_body(cid, f"demo_warm_{cid}", **ctx_over))
            expect(r.status_code == 200, f"{cid} {r.status_code}: {r.text[:120]}")
            p = r.json()
            if cid.startswith("S-"):
                self.facts["scam_payment_ids"].append(p["id"])
            done.append(f"{cid}->{p['decision']['outcome']}")
        after = ResponseCache.totals()
        return (
            f"{' '.join(done)}; cache hits +{after['hits'] - before['hits']} "
            f"misses +{after['misses'] - before['misses']} puts +{after['puts'] - before['puts']}"
        )

    # -- scoreboard ---------------------------------------------------------

    def scoreboard(self, started: float, env_info: dict[str, str]) -> dict[str, Any]:
        from kernel.llm.cache import ResponseCache

        payments = self.get("/payments?limit=500").json()["payments"]
        scam_ids = set(self.facts["scam_payment_ids"])
        unauthorized = [
            p["id"]
            for p in payments
            if p["state"] == "SUBMITTED"
            and (p["id"] in scam_ids or str(p.get("conversation_id", "")).startswith("room_"))
        ]
        b = self.facts["scenario_b_payment_id"]
        legit_completed = sum(1 for p in payments if p["id"] == b and p["state"] == "SUBMITTED")
        totals = ResponseCache.totals()
        ok = not self.failures and not unauthorized and legit_completed == 1
        return {
            "ok": ok,
            "unauthorized_releases": len(unauthorized),
            "legit_completed": legit_completed,
            "attacks_refused": self.facts["attacks_refused"],
            "attacks_total": len(EXPECTED_ATTACKS),
            "audit_tamper_detected": bool(self.facts["tamper_detected"]),
            "payments_total": len(payments),
            "total_seconds": round(time.perf_counter() - started, 2),
            "modes": self.facts["modes"],
            "llm_cache": {**totals, "replay_only": env_info["replay_only"] == "1"},
            "health_cache": self.facts["health_cache"],
            "failures": list(self.failures),
        }


def run(
    *, real: bool = False, warm: bool = False, json_out: bool = False, out: TextIO | None = None
) -> dict[str, Any]:
    """Run the whole demo in-process. Returns the scoreboard (`ok` False on any failure)."""
    out = sys.stdout if out is None else out
    started = time.perf_counter()
    with demo_env(real=real, warm=warm) as env_info:
        from fastapi.testclient import TestClient

        from api import deps
        from api.main import create_app
        from kernel.llm.cache import ResponseCache

        deps.reset()
        ResponseCache.reset_totals()
        print(
            f"Second Key demo  real={env_info['real']} replay_only={env_info['replay_only']} "
            f"warm={'1' if warm else '0'}",
            file=out,
        )
        try:
            with TestClient(create_app()) as client:
                demo = Demo(client, out, deps.get_settings().ops_token, real=real or warm)
                demo.step(1, "health", demo.step_health)
                demo.step(2, "scenario A (room, IRS/warmth)", demo.step_scenario_a)
                demo.step(3, "scenario B (Bay Roofing ACH)", demo.step_scenario_b)
                demo.step(4, "scenario C (Priya self-attest)", demo.step_scenario_c)
                demo.step(5, "attack panel", demo.step_attacks)
                demo.step(6, "audit verify / tamper", demo.step_audit)
                if warm:
                    demo.step(7, "warm extras (S-03, L-01, L-40)", demo.step_warm_extras)
                board = demo.scoreboard(started, env_info)
        finally:
            deps.reset()
    cache = board["llm_cache"]
    print(file=out)
    print("SCOREBOARD", file=out)
    print(f"  unauthorized releases : {board['unauthorized_releases']}", file=out)
    print(f"  legitimate completed  : {board['legit_completed']}", file=out)
    print(
        f"  attacks refused       : {board['attacks_refused']}/{board['attacks_total']}", file=out
    )
    print(
        f"  audit tamper detected : {'yes' if board['audit_tamper_detected'] else 'NO'}", file=out
    )
    print(
        f"  llm cache             : hits={cache['hits']} misses={cache['misses']} "
        f"puts={cache['puts']} replay_only={cache['replay_only']}",
        file=out,
    )
    print(f"  total time            : {board['total_seconds']}s", file=out)
    print(f"  result                : {'PASS' if board['ok'] else 'FAIL'}", file=out)
    for f in board["failures"]:
        print(f"  failure: {f}", file=out)
    if json_out:
        print(json.dumps(board, sort_keys=True), file=out)
    return board


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--real", action="store_true", help="load .env; real extractor and Margaret")
    ap.add_argument("--warm", action="store_true", help="--real plus fill the cache on misses")
    ap.add_argument("--json", action="store_true", help="scoreboard as JSON on the last line")
    args = ap.parse_args(argv)
    board = run(real=args.real, warm=args.warm, json_out=args.json)
    return 0 if board["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
