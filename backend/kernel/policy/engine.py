"""Versioned rules engine. `decide` is pure: (payment, signals, context, policy) -> Decision.

Fail closed:
- load_policy refuses anything ambiguous (unknown identifier, default ALLOW, duplicate id ...).
- No rule fires -> policy default (HOLD) with rule id DEFAULT.
- A rule that cannot be evaluated counts as a fired HOLD with rule id X-01, so a broken rule
  can never lower the outcome below HOLD and a DENY from another rule still wins.
- fail_closed(d, "X-00") is what callers use when the extractor fails; it never lowers.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from kernel.llm.types import Signal
from kernel.models import AccountContext, Decision, Outcome, PaymentIn, StrictModel
from kernel.policy.env import KNOWN_IDENTIFIERS, build_env
from kernel.policy.expr import EvalError, Node, ParseError, evaluate, free_identifiers, parse

log = logging.getLogger("second_key.policy")

V1_PATH = Path(__file__).with_name("v1.yaml")
DEFAULT_RULE_ID = "DEFAULT"
EVAL_ERROR_RULE_ID = "X-01"
EXTRACTOR_FAIL_RULE_ID = "X-00"
_RESERVED_PREFIX = "X-"


class PolicyLoadError(ValueError):
    """The policy file is malformed or unsafe. Raised at load time, never at decide time."""


class Rule(StrictModel):
    id: str
    when: str
    outcome: Outcome


@dataclass(frozen=True)
class Policy:
    version: str
    rules: tuple[Rule, ...]
    default: Outcome
    precedence: tuple[Outcome, Outcome, Outcome]
    compiled: Mapping[str, Node]

    def rank(self, outcome: Outcome) -> int:
        """Lower is stronger. DENY is 0 under the only precedence load_policy accepts at the top."""
        return self.precedence.index(outcome)


def _outcome(raw: object, where: str) -> Outcome:
    if isinstance(raw, str):
        try:
            return Outcome(raw)
        except ValueError:
            pass
    raise PolicyLoadError(f"{where}: outcome must be one of ALLOW, HOLD, DENY, got {raw!r}")


def load_policy(path: Path) -> Policy:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PolicyLoadError(f"policy file not found: {path}") from None
    except yaml.YAMLError as e:
        raise PolicyLoadError(f"invalid YAML in {path}: {e}") from None
    if not isinstance(raw, dict):
        raise PolicyLoadError(f"{path}: top level must be a mapping")

    version = raw.get("version")
    if not isinstance(version, str) or not version:
        raise PolicyLoadError(f"{path}: 'version' must be a non-empty string")

    default = _outcome(raw.get("default"), f"{version} default")
    if default is Outcome.ALLOW:
        raise PolicyLoadError(f"{version}: default must not be ALLOW (fail closed)")

    prec_raw = raw.get("precedence")
    if not isinstance(prec_raw, list) or len(prec_raw) != 3:
        raise PolicyLoadError(f"{version}: precedence must list DENY, HOLD and ALLOW once each")
    prec = tuple(_outcome(x, f"{version} precedence") for x in prec_raw)
    if set(prec) != set(Outcome) or len(prec) != 3:
        raise PolicyLoadError(f"{version}: precedence must be a permutation of DENY, HOLD, ALLOW")
    if prec[-1] is not Outcome.ALLOW:
        raise PolicyLoadError(f"{version}: precedence must rank ALLOW last (fail closed)")
    precedence: tuple[Outcome, Outcome, Outcome] = (prec[0], prec[1], prec[2])

    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise PolicyLoadError(f"{version}: 'rules' must be a non-empty list")

    rules: list[Rule] = []
    compiled: dict[str, Node] = {}
    for idx, item in enumerate(rules_raw):
        where = f"{version} rules[{idx}]"
        if not isinstance(item, dict):
            raise PolicyLoadError(f"{where}: each rule must be a mapping")
        unknown = set(item) - {"id", "when", "outcome"}
        if unknown:
            raise PolicyLoadError(f"{where}: unknown keys {sorted(unknown)}")
        rid = item.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise PolicyLoadError(f"{where}: 'id' must be a non-empty string")
        where = f"{version} rule {rid}"
        if rid == DEFAULT_RULE_ID or rid.startswith(_RESERVED_PREFIX):
            raise PolicyLoadError(f"{where}: id is reserved for the engine")
        if rid in compiled:
            raise PolicyLoadError(f"{where}: duplicate id {rid}")
        when = item.get("when")
        if not isinstance(when, str) or not when.strip():
            raise PolicyLoadError(f"{where}: 'when' must be a non-empty string")
        if "outcome" not in item:
            raise PolicyLoadError(f"{where}: missing 'outcome'")
        outcome = _outcome(item["outcome"], where)
        try:
            node = parse(when)
        except ParseError as e:
            raise PolicyLoadError(f"{where}: cannot parse 'when': {e}") from None
        unknown_ids = free_identifiers(node) - KNOWN_IDENTIFIERS
        if unknown_ids:
            raise PolicyLoadError(f"{where}: unknown identifier(s) {sorted(unknown_ids)}")
        rules.append(Rule(id=rid, when=when, outcome=outcome))
        compiled[rid] = node

    policy = Policy(
        version=version,
        rules=tuple(rules),
        default=default,
        precedence=precedence,
        compiled=compiled,
    )
    log.info("policy.loaded", extra={"policy_version": version, "rules": len(rules)})
    return policy


def decide(
    p: PaymentIn, signals: Sequence[Signal], ctx: AccountContext, policy: Policy
) -> Decision:
    """Pure. Every rule is evaluated; the strongest outcome among those that fired wins."""
    env = build_env(p, signals, ctx)
    fired: list[tuple[str, Outcome]] = []
    for rule in policy.rules:
        try:
            result = evaluate(policy.compiled[rule.id], env)
            if not isinstance(result, bool):
                raise EvalError(f"'when' must be boolean, got {type(result).__name__}")
        except EvalError:
            fired.append((EVAL_ERROR_RULE_ID, Outcome.HOLD))
            continue
        if result:
            fired.append((rule.id, rule.outcome))

    if not fired:
        return Decision(
            outcome=policy.default, rule_ids=(DEFAULT_RULE_ID,), policy_version=policy.version
        )
    outcome = min((o for _, o in fired), key=policy.rank)
    rule_ids: list[str] = []
    for rid, _ in fired:
        if rid not in rule_ids:
            rule_ids.append(rid)
    return Decision(outcome=outcome, rule_ids=tuple(rule_ids), policy_version=policy.version)


def fail_closed(d: Decision, rule_id: str) -> Decision:
    """Downgrade ALLOW to HOLD and tag the reason. Never lowers HOLD or DENY."""
    outcome = Outcome.HOLD if d.outcome is Outcome.ALLOW else d.outcome
    rule_ids = d.rule_ids if rule_id in d.rule_ids else (*d.rule_ids, rule_id)
    return Decision(outcome=outcome, rule_ids=rule_ids, policy_version=d.policy_version)
