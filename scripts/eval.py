#!/usr/bin/env python3
"""Second Key eval: run every fixture case through the kernel library and score it.

Headline numbers: unauthorized_releases (scam cases that reached SUBMITTED) and legit_completed
(legit cases that reached SUBMITTED within expected.max_friction_steps). Both come from the real
kernel code path (create_payment -> attest -> issue_certificate -> release), not from HTTP.

Usage (either cwd works; sys.path is set up below):
    cd backend && MOCK_EXTRACTOR=1 uv run python ../scripts/eval.py \
        --suite ../fixtures/cases --out ../eval/latest.json
    uv run --project backend python scripts/eval.py --real --ids S-04,S-05 --agreement 10 \
        --out eval/latest_real.json

Flags:
    --mock          force MockExtractor (keyword heuristics over conversation text).
    --real          force the Claude extractor; loads .env; requires ANTHROPIC_API_KEY.
    --ids A,B,C     run a subset of case ids.
    --agreement N   with a key: run N cases through BOTH extractors, record extractor_agreement.
    --shared-evidence  append fixtures/evidence.json items to each conversation (see README).

Exit code 1 if unauthorized_releases > 0 or legit_completed < 38. Never edits a case.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
for p in (str(REPO_ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fixtures.validate_cases import load_cases, validate_cases  # noqa: E402

from kernel.clock import FakeClock  # noqa: E402
from kernel.llm.factory import build_extractor  # noqa: E402
from kernel.llm.mock_extractor import MockExtractor  # noqa: E402
from kernel.llm.types import SIGNAL_KINDS, EvidenceItem, Extractor, ExtractorResult  # noqa: E402
from kernel.models import (  # noqa: E402
    AccountContext,
    Capability,
    Outcome,
    PaymentIn,
    Refusal,
    State,
)
from kernel.policy.engine import DEFAULT_RULE_ID, V1_PATH, Policy, load_policy  # noqa: E402
from kernel.rail import NullTransferRail, RailError  # noqa: E402
from kernel.service import Kernel  # noqa: E402

CUSTOMER_ID = "acc_margaret"
OPS_ID = "ops_1"
LEGIT_MIN = 38
MOCK_NOTE = (
    "MockExtractor is keyword-based over conversation text; "
    "numbers with the real extractor are separate"
)
SHARED_EVIDENCE = REPO_ROOT / "fixtures" / "evidence.json"


# ----------------------------------------------------------------------------- inputs


def load_env(args: argparse.Namespace) -> dict[str, str]:
    """os.environ, plus .env underneath it when a real key is needed. Never exports anything."""
    env: dict[str, str] = dict(os.environ)
    if args.real or args.agreement:
        from dotenv import dotenv_values

        for k, v in dotenv_values(REPO_ROOT / ".env").items():
            if v is not None and not env.get(k):
                env[k] = v
    if args.mock:
        env["MOCK_EXTRACTOR"] = "1"
    if args.real:
        env.pop("MOCK_EXTRACTOR", None)
        if not env.get("ANTHROPIC_API_KEY", "").strip():
            sys.exit("--real requires ANTHROPIC_API_KEY (in the environment or .env)")
    return env


def shared_evidence_items() -> tuple[EvidenceItem, ...]:
    raw = json.loads(SHARED_EVIDENCE.read_text(encoding="utf-8"))
    return tuple(
        EvidenceItem(id=str(e["id"]), speaker=str(e.get("kind", "bank")), text=str(e["text"]))
        for e in raw
    )


def to_payment(case: Mapping[str, Any]) -> PaymentIn:
    return PaymentIn.model_validate(
        {**case["payment"], "conversation_id": case["id"]}, strict=False
    )


def to_context(case: Mapping[str, Any]) -> AccountContext:
    return AccountContext.model_validate(case["account_context"], strict=False)


def to_conversation(
    case: Mapping[str, Any], shared: tuple[EvidenceItem, ...]
) -> tuple[EvidenceItem, ...]:
    conv = tuple(EvidenceItem.model_validate(t) for t in case["conversation"])
    return conv + shared


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def git_dirty() -> bool | None:
    """True when the working tree has uncommitted changes (the sha alone is then not enough)."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


# ----------------------------------------------------------------------------- test suites

TESTS_DIR = BACKEND / "tests"
_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def (test_\w+)\s*\(", re.MULTILINE)
_PROFILE = re.compile(r'register_profile\(\s*"(\w+)",\s*max_examples=(\d+)')
_INVARIANT_MODULE = re.compile(r"^test_i([1-7])_")


def scan_tests(subdir: str) -> dict[str, Any]:
    """Count `def test_*` functions per file by text scan. Counts only; no PASS claim."""
    root = TESTS_DIR / subdir
    files: dict[str, int] = {}
    for f in sorted(root.glob("test_*.py")) if root.is_dir() else []:
        files[f.name] = len(_TEST_DEF.findall(f.read_text(encoding="utf-8")))
    return {
        "dir": str(root.relative_to(REPO_ROOT)),
        "files": files,
        "test_functions": sum(files.values()),
    }


def hypothesis_profiles() -> dict[str, int]:
    conftest = TESTS_DIR / "conftest.py"
    if not conftest.is_file():
        return {}
    return {name: int(n) for name, n in _PROFILE.findall(conftest.read_text(encoding="utf-8"))}


def property_suite() -> dict[str, Any]:
    scan = scan_tests("property")
    invariants: dict[str, list[str]] = {}
    for name in scan["files"]:
        m = _INVARIANT_MODULE.match(name)
        if m:
            invariants.setdefault(f"I{m.group(1)}", []).append(name)
    covered = sorted(invariants)
    return {
        **scan,
        "hypothesis_profiles": hypothesis_profiles(),
        "invariant_modules": {k: invariants[k] for k in covered},
        "invariants_covered": covered,
        "invariants_missing": [f"I{i}" for i in range(1, 8) if f"I{i}" not in invariants],
        "note": "counts from a text scan of def test_*; not a pass/fail claim",
    }


class _CacheCounter(logging.Handler):
    """Counts the ClaudeExtractor's own cache_hit log field. hits+misses == real calls made."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.hits = 0
        self.misses = 0

    def emit(self, record: logging.LogRecord) -> None:
        hit = getattr(record, "cache_hit", None)
        if hit is True:
            self.hits += 1
        elif hit is False:
            self.misses += 1


# ----------------------------------------------------------------------------- one case


def _signal_rows(signals: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {"kind": s.kind, "score": round(float(s.score), 3), "source_id": s.source_id}
        for s in signals
    ]


def _rules_ok(
    fired: tuple[str, ...], outcome: Outcome, expected: list[str], policy: Policy
) -> bool:
    """Fired ids minus DEFAULT minus ALLOW rules overridden by a HOLD/DENY must be allowed.

    An empty allowed list means only DEFAULT may fire. X-00/X-01 are never allowed: they mean
    the extractor or a rule failed, and that must show up as a mismatch.
    """
    allow_rules = {r.id for r in policy.rules if r.outcome is Outcome.ALLOW}
    considered = set(fired) - {DEFAULT_RULE_ID}
    if outcome is not Outcome.ALLOW:
        considered -= allow_rules
    return considered <= set(expected)


def run_case(
    case: Mapping[str, Any],
    *,
    policy: Policy,
    extractor: Extractor,
    shared: tuple[EvidenceItem, ...],
) -> dict[str, Any]:
    cid = str(case["id"])
    is_legit = cid.startswith("L-")
    expected = case["expected"]
    kernel = Kernel(
        ":memory:",
        policy=policy,
        clock=FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC)),
        extractor=extractor,
        rail=NullTransferRail(),
    )
    payment, decision = kernel.create_payment(
        to_payment(case), to_context(case), to_conversation(case, shared)
    )
    record = kernel.get(payment.id)
    outcome = decision.outcome
    friction = 0
    error: str | None = None
    pid = payment.id

    def finish() -> None:
        nonlocal payment
        cert = kernel.issue_certificate(pid, OPS_ID, Capability.BANK_REVIEW)
        payment = kernel.release(pid, cert.id, cert.nonce)

    try:
        if is_legit:
            if outcome is Outcome.ALLOW:
                finish()
            elif outcome is Outcome.HOLD:
                kernel.attest(pid, CUSTOMER_ID, Capability.CUSTOMER_CHECKIN, note="eval checkin")
                friction = 1
                payment = kernel.attest(pid, OPS_ID, Capability.BANK_REVIEW, note="eval review")
                friction = 2
                if payment.state is State.ELIGIBLE_TO_SUBMIT:
                    finish()
            # DENY: nothing can complete it (I6). Leave it.
        else:
            # Scam: nobody in the loop. ALLOW means the kernel would let a certificate through.
            if outcome is Outcome.ALLOW:
                finish()
    except (Refusal, RailError) as e:
        error = str(e)

    final = kernel.get(pid).payment.state
    submitted = final is State.SUBMITTED
    completed = is_legit and submitted and friction <= int(expected["max_friction_steps"])
    outcome_ok = outcome.value == expected["outcome"]
    rules_ok = _rules_ok(decision.rule_ids, outcome, list(expected["allowed_rule_ids"]), policy)
    return {
        "id": cid,
        "title": case["title"],
        "kind": "legit" if is_legit else "scam",
        "signals_required": bool(case.get("signals_required")),
        "tags": list(case.get("tags", [])),
        "expected_outcome": expected["outcome"],
        "outcome": outcome.value,
        "outcome_ok": outcome_ok,
        "rule_ids": list(decision.rule_ids),
        "allowed_rule_ids": list(expected["allowed_rule_ids"]),
        "rules_ok": rules_ok,
        "signals": _signal_rows(record.signals),
        "friction_steps": friction,
        "max_friction_steps": int(expected["max_friction_steps"]),
        "final_state": final.value,
        "completed": completed,
        "unauthorized_release": (not is_legit) and submitted,
        "caught": (not is_legit) and not submitted,
        "error": error,
        "audit_ok": kernel.audit_verify().ok,
    }


# ----------------------------------------------------------------------------- agreement


def _kinds_present(res: ExtractorResult) -> dict[str, float]:
    maxes = dict.fromkeys(SIGNAL_KINDS, 0.0)
    for s in res.signals:
        maxes[s.kind] = max(maxes[s.kind], float(s.score))
    return maxes


def extractor_agreement(
    cases: list[Mapping[str, Any]],
    *,
    real: Extractor,
    shared: tuple[EvidenceItem, ...],
    policy: Policy,
) -> dict[str, Any]:
    """Run N cases through the mock and the real extractor; compare per-kind presence and the
    decision each set of signals would produce under the same policy and context."""
    from kernel.policy.engine import decide

    mock = MockExtractor()
    per_kind = {k: {"agree": 0, "mock_only": 0, "real_only": 0, "neither": 0} for k in SIGNAL_KINDS}
    rows: list[dict[str, Any]] = []
    outcome_agree = 0
    for case in cases:
        p = to_payment(case)
        ctx = to_context(case)
        conv = to_conversation(case, shared)
        m = mock.extract(conv, p)
        try:
            r = real.extract(conv, p)
            real_ok = True
        except Exception as e:  # noqa: BLE001  the real extractor failing is data here
            r, real_ok = ExtractorResult(), False
            print(f"  agreement: real extractor failed on {case['id']}: {type(e).__name__}")
        mk, rk = _kinds_present(m), _kinds_present(r)
        for k in SIGNAL_KINDS:
            a, b = mk[k] > 0, rk[k] > 0
            bucket = (
                "agree"
                if a == b and a
                else "neither"
                if a == b
                else "mock_only"
                if a
                else "real_only"
            )
            per_kind[k][bucket] += 1
        dm = decide(p, m.signals, ctx, policy).outcome.value
        dr = decide(p, r.signals, ctx, policy).outcome.value if real_ok else "X-00"
        outcome_agree += int(dm == dr)
        rows.append(
            {
                "id": case["id"],
                "mock_kinds": {k: round(v, 2) for k, v in mk.items() if v > 0},
                "real_kinds": {k: round(v, 2) for k, v in rk.items() if v > 0},
                "real_ok": real_ok,
                "outcome_mock": dm,
                "outcome_real": dr,
            }
        )
    n = len(cases)
    summary = {}
    for k, b in per_kind.items():
        both_or_neither = b["agree"] + b["neither"]
        summary[k] = {**b, "agreement": round(both_or_neither / n, 3) if n else None}
    return {
        "cases": [c["id"] for c in cases],
        "n": n,
        "presence_metric": "a kind counts as present when any signal of that kind has score > 0",
        "per_kind": summary,
        "outcome_agreement": round(outcome_agree / n, 3) if n else None,
        "rows": rows,
    }


# ----------------------------------------------------------------------------- report


def print_table(rows: list[dict[str, Any]]) -> None:
    hdr = (
        f"{'id':<5} {'exp':<5} {'got':<5} {'ok':<4} {'rules':<22} {'state':<19} {'steps':>5}  title"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ok = ("o" if r["outcome_ok"] else "O") + ("r" if r["rules_ok"] else "R")
        if r["unauthorized_release"]:
            ok += "!"
        print(
            f"{r['id']:<5} {r['expected_outcome']:<5} {r['outcome']:<5} {ok:<4} "
            f"{','.join(r['rule_ids']):<22} {r['final_state']:<19} "
            f"{r['friction_steps']:>5}  {r['title'][:48]}"
        )
    print("ok column: o/O outcome match/mismatch, r/R rules match/mismatch, ! unauthorized release")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--suite", default=str(REPO_ROOT / "fixtures" / "cases"))
    ap.add_argument("--out", default=str(REPO_ROOT / "eval" / "latest.json"))
    ap.add_argument("--mock", action="store_true", help="force MockExtractor")
    ap.add_argument("--real", action="store_true", help="force the Claude extractor (needs a key)")
    ap.add_argument("--ids", default="", help="comma-separated subset of case ids")
    ap.add_argument("--agreement", type=int, default=0, metavar="N", help="mock vs real on N cases")
    ap.add_argument(
        "--shared-evidence",
        action="store_true",
        help="append fixtures/evidence.json items to every conversation as citable evidence",
    )
    args = ap.parse_args(argv)
    if args.mock and args.real:
        ap.error("--mock and --real are exclusive")

    env = load_env(args)
    policy = load_policy(V1_PATH)
    extractor, mode = build_extractor(env)
    if args.real and mode != "real":
        sys.exit("--real given but the factory chose the mock extractor")
    cache_counter = _CacheCounter()
    claude_log = logging.getLogger("second_key.llm.claude")
    claude_log.addHandler(cache_counter)
    if claude_log.level == logging.NOTSET or claude_log.level > logging.INFO:
        claude_log.setLevel(logging.INFO)

    all_cases = load_cases(args.suite)
    schema_errors = validate_cases(all_cases)
    wanted = [s.strip() for s in args.ids.split(",") if s.strip()]
    if wanted:
        by_id = {c["id"]: c for c in all_cases}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            sys.exit(f"unknown case id(s): {missing}")
        cases = [by_id[w] for w in wanted]
    else:
        cases = all_cases
    shared = shared_evidence_items() if args.shared_evidence else ()

    print(f"extractor_mode: {mode}  policy: {policy.version}  cases: {len(cases)}")
    if mode == "mock":
        print(f"NOTE: {MOCK_NOTE}")
    if schema_errors:
        print(f"WARNING: {len(schema_errors)} fixture schema error(s); first: {schema_errors[0]}")

    rows = [run_case(c, policy=policy, extractor=extractor, shared=shared) for c in cases]
    legit = [r for r in rows if r["kind"] == "legit"]
    scams = [r for r in rows if r["kind"] == "scam"]
    per_rule: dict[str, int] = {}
    for r in rows:
        for rid in r["rule_ids"]:
            per_rule[rid] = per_rule.get(rid, 0) + 1
    sig_req = [r for r in scams if r["signals_required"]]

    result: dict[str, Any] = {
        "unauthorized_releases": sum(1 for r in scams if r["unauthorized_release"]),
        "legit_completed": sum(1 for r in legit if r["completed"]),
        "legit_total": len(legit),
        "scam_total": len(scams),
        "avg_friction_steps": (
            round(sum(r["friction_steps"] for r in legit) / len(legit), 3) if legit else 0.0
        ),
        "outcome_mismatches": [r["id"] for r in rows if not r["outcome_ok"]],
        "rule_mismatches": [r["id"] for r in rows if not r["rules_ok"]],
        "per_rule_hits": dict(sorted(per_rule.items())),
        "signals_required_total": len(sig_req),
        "signals_required_caught": sum(1 for r in sig_req if r["caught"]),
        "scams_caught": sum(1 for r in scams if r["caught"]),
        "audit_ok_all": all(r["audit_ok"] for r in rows),
        "extractor_mode": mode,
        "extractor_model": env.get("ANTHROPIC_MODEL", "") if mode == "real" else None,
        "shared_evidence_included": bool(shared),
        "policy_version": policy.version,
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": str(Path(args.suite).resolve()),
        "subset": wanted or None,
        "schema_errors": schema_errors,
        "mock_note": MOCK_NOTE if mode == "mock" else None,
        "property_suite": property_suite(),
        "suite_counts": {k: scan_tests(k)["test_functions"] for k in ("unit", "api", "voice")},
        "cases": rows,
    }

    if args.agreement > 0:
        if mode == "real":
            real_x = extractor
        else:
            real_x, real_mode = build_extractor({**env, "MOCK_EXTRACTOR": ""})
            if real_mode != "real":
                real_x = None
        if real_x is None:
            print("agreement: skipped (no ANTHROPIC_API_KEY)")
            result["extractor_agreement"] = None
        else:
            picked = cases[: args.agreement]
            print(f"agreement: running {len(picked)} case(s) through mock and real extractors")
            result["extractor_agreement"] = extractor_agreement(
                picked, real=real_x, shared=shared, policy=policy
            )

    result["llm_cache"] = (
        {"hits": cache_counter.hits, "misses": cache_counter.misses}
        if cache_counter.hits or cache_counter.misses
        else None
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print_table(rows)
    print()
    print(
        f"unauthorized_releases={result['unauthorized_releases']}  "
        f"legit_completed={result['legit_completed']}/{result['legit_total']}  "
        f"scams_caught={result['scams_caught']}/{result['scam_total']}  "
        f"avg_friction_steps={result['avg_friction_steps']}  "
        f"signals_required_caught={result['signals_required_caught']}/{result['signals_required_total']}"
    )
    print(f"outcome_mismatches={result['outcome_mismatches']}")
    print(f"rule_mismatches={result['rule_mismatches']}")
    print(f"per_rule_hits={result['per_rule_hits']}")
    agr = result.get("extractor_agreement")
    if agr:
        kinds = ", ".join(f"{k}={v['agreement']}" for k, v in agr["per_kind"].items())
        print(f"extractor_agreement (n={agr['n']}): outcome={agr['outcome_agreement']}  {kinds}")
    ps = result["property_suite"]
    print(
        f"property_suite: {ps['test_functions']} test functions in {len(ps['files'])} files, "
        f"profiles={ps['hypothesis_profiles']}, invariants={ps['invariants_covered']}  "
        f"suite_counts={result['suite_counts']}"
    )
    if result["llm_cache"]:
        print(f"llm_cache: {result['llm_cache']}")
    print(f"wrote {out}")

    full_suite = not wanted
    bad = result["unauthorized_releases"] > 0 or (
        full_suite and result["legit_completed"] < LEGIT_MIN
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
