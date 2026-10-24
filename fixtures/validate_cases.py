#!/usr/bin/env python3
"""Schema check for fixtures/cases/*.json. No dependencies. Run with: python3 -I fixtures/validate_cases.py

Importable by scripts/eval.py:
    from fixtures.validate_cases import load_cases, validate_cases
"""
import json
import os
import sys

CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases")

OUTCOMES = {"ALLOW", "HOLD", "DENY"}
RAILS = {"WIRE", "ACH", "ZELLE", "CARD"}
SPEAKERS = {"caller", "margaret", "priya", "bank"}
RULE_IDS = {"D-01", "H-01", "H-02", "H-03", "H-04", "H-05", "H-06", "A-01"}
TOP_KEYS = {"id", "title", "tags", "signals_required", "conversation", "payment",
            "account_context", "expected", "review_note"}
CTX_KEYS = {"baseline_90d_cents", "known_billers", "prior_payees", "mule_list",
            "known_biller_cap_cents"}
EXPECTED_KEYS = {"outcome", "allowed_rule_ids", "max_friction_steps"}


def load_cases(cases_dir=CASES_DIR):
    cases = []
    for name in sorted(os.listdir(cases_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(cases_dir, name), encoding="utf-8") as f:
            c = json.load(f)
        c["_file"] = name
        cases.append(c)
    return cases


def _check(errors, cond, msg):
    if not cond:
        errors.append(msg)


def validate_case(c):
    e = []
    cid = c.get("id", c.get("_file"))
    _check(e, set(c) - {"_file"} == TOP_KEYS,
           f"{cid}: top-level keys {sorted(set(c) - {'_file'} ^ TOP_KEYS)} mismatch")
    _check(e, c["_file"] == f"{c.get('id')}.json", f"{cid}: file name does not match id")
    _check(e, isinstance(c.get("title"), str) and c["title"], f"{cid}: title")
    _check(e, isinstance(c.get("tags"), list) and all(isinstance(t, str) for t in c["tags"]),
           f"{cid}: tags")
    _check(e, isinstance(c.get("signals_required"), bool), f"{cid}: signals_required must be bool")
    _check(e, isinstance(c.get("review_note"), str) and "\n" not in c["review_note"],
           f"{cid}: review_note must be one line")

    # conversation
    conv = c.get("conversation")
    _check(e, isinstance(conv, list), f"{cid}: conversation must be a list")
    if isinstance(conv, list):
        ids = [t.get("id") for t in conv]
        _check(e, len(ids) == len(set(ids)), f"{cid}: duplicate EV ids")
        for i, t in enumerate(conv):
            _check(e, set(t) == {"id", "speaker", "text"}, f"{cid}: turn {i} keys")
            _check(e, t.get("id") == f"EV-{i + 1:04d}", f"{cid}: turn {i} id should be EV-{i + 1:04d}")
            _check(e, t.get("speaker") in SPEAKERS, f"{cid}: turn {i} speaker {t.get('speaker')}")
            _check(e, isinstance(t.get("text"), str) and t["text"].strip(), f"{cid}: turn {i} text")
        _check(e, len(conv) == 0 or 3 <= len(conv) <= 8 or len(conv) == 2,
               f"{cid}: conversation length {len(conv)} outside 0 or 2..8")

    # payment
    p = c.get("payment", {})
    _check(e, set(p) == {"account_id", "amount_cents", "currency", "beneficiary", "rail"},
           f"{cid}: payment keys")
    _check(e, p.get("account_id") == "acc_margaret", f"{cid}: account_id")
    _check(e, p.get("currency") == "USD", f"{cid}: currency")
    _check(e, isinstance(p.get("amount_cents"), int) and p["amount_cents"] > 0, f"{cid}: amount_cents")
    _check(e, p.get("rail") in RAILS, f"{cid}: rail {p.get('rail')}")
    b = p.get("beneficiary", {})
    _check(e, set(b) == {"name", "account_ref", "is_new"}, f"{cid}: beneficiary keys")
    _check(e, isinstance(b.get("name"), str) and b["name"], f"{cid}: beneficiary.name")
    _check(e, isinstance(b.get("account_ref"), str) and b["account_ref"].startswith("ext_"),
           f"{cid}: beneficiary.account_ref must start with ext_")
    _check(e, isinstance(b.get("is_new"), bool), f"{cid}: beneficiary.is_new must be bool")

    # account_context
    ctx = c.get("account_context", {})
    _check(e, set(ctx) == CTX_KEYS, f"{cid}: account_context keys {sorted(set(ctx) ^ CTX_KEYS)}")
    _check(e, isinstance(ctx.get("baseline_90d_cents"), int) and ctx["baseline_90d_cents"] > 0,
           f"{cid}: baseline_90d_cents")
    _check(e, isinstance(ctx.get("known_biller_cap_cents"), int) and ctx["known_biller_cap_cents"] > 0,
           f"{cid}: known_biller_cap_cents")
    for k in ("known_billers", "prior_payees", "mule_list"):
        _check(e, isinstance(ctx.get(k), list) and all(isinstance(x, str) for x in ctx.get(k, [])),
               f"{cid}: {k} must be list of str")
    # is_new consistency: a prior payee by ref cannot be new
    if isinstance(ctx.get("prior_payees"), list) and isinstance(b.get("is_new"), bool):
        _check(e, not (b["account_ref"] in ctx["prior_payees"] and b["is_new"]),
               f"{cid}: account_ref in prior_payees but is_new is true")
        _check(e, not (b["account_ref"] not in ctx["prior_payees"] and not b["is_new"]),
               f"{cid}: account_ref not in prior_payees but is_new is false")

    # expected
    x = c.get("expected", {})
    _check(e, set(x) == EXPECTED_KEYS, f"{cid}: expected keys")
    _check(e, x.get("outcome") in OUTCOMES, f"{cid}: expected.outcome")
    _check(e, isinstance(x.get("allowed_rule_ids"), list) and set(x.get("allowed_rule_ids", [])) <= RULE_IDS,
           f"{cid}: allowed_rule_ids contains unknown rule id")
    _check(e, isinstance(x.get("max_friction_steps"), int), f"{cid}: max_friction_steps")

    is_legit = str(c.get("id", "")).startswith("L-")
    is_scam = str(c.get("id", "")).startswith("S-")
    _check(e, is_legit or is_scam, f"{cid}: id must start with L- or S-")
    if is_legit:
        _check(e, "legit" in c.get("tags", []), f"{cid}: legit case missing 'legit' tag")
        _check(e, x.get("outcome") in {"ALLOW", "HOLD"}, f"{cid}: legit case may not expect DENY")
        _check(e, b.get("account_ref") not in ctx.get("mule_list", []),
               f"{cid}: legit payee is on the mule list")
        _check(e, x.get("max_friction_steps") in (0, 1, 2), f"{cid}: legit max_friction_steps must be 0..2")
        if x.get("outcome") == "ALLOW":
            _check(e, x.get("max_friction_steps") == 0, f"{cid}: ALLOW must have 0 friction")
        _check(e, c.get("signals_required") is False, f"{cid}: legit case cannot be signals_required")
    if is_scam:
        _check(e, "scam" in c.get("tags", []), f"{cid}: scam case missing 'scam' tag")
        _check(e, x.get("outcome") in {"HOLD", "DENY"}, f"{cid}: scam case may not expect ALLOW")
        _check(e, x.get("max_friction_steps") == 99, f"{cid}: scam max_friction_steps must be 99")
        on_mule = b.get("account_ref") in ctx.get("mule_list", [])
        if on_mule:
            _check(e, x.get("outcome") == "DENY", f"{cid}: payee on mule list must expect DENY")
            _check(e, "D-01" in x.get("allowed_rule_ids", []), f"{cid}: mule case must allow D-01")
        if c.get("signals_required"):
            amt = p.get("amount_cents", 0)
            base = ctx.get("baseline_90d_cents", 1)
            _check(e, amt < 3 * base, f"{cid}: signals_required but amount >= 3x baseline")
            _check(e, not on_mule, f"{cid}: signals_required but payee on mule list")
            _check(e, not (b.get("is_new") and p.get("rail") in {"WIRE", "ZELLE"}),
                   f"{cid}: signals_required but new payee on WIRE/ZELLE (H-01 would catch it)")

    # text hygiene: no em dashes anywhere
    blob = json.dumps(c, ensure_ascii=False)
    _check(e, chr(0x2014) not in blob, f"{cid}: contains an em dash")
    return e


def validate_cases(cases):
    errors = []
    ids = [c.get("id") for c in cases]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case ids")
    n_l = sum(1 for i in ids if str(i).startswith("L-"))
    n_s = sum(1 for i in ids if str(i).startswith("S-"))
    if n_l != 40:
        errors.append(f"expected 40 legit cases, found {n_l}")
    if n_s != 20:
        errors.append(f"expected 20 scam cases, found {n_s}")
    if sorted(i for i in ids if str(i).startswith("L-")) != [f"L-{i:02d}" for i in range(1, 41)]:
        errors.append("legit ids must be L-01..L-40")
    if sorted(i for i in ids if str(i).startswith("S-")) != [f"S-{i:02d}" for i in range(1, 21)]:
        errors.append("scam ids must be S-01..S-20")
    n_sig = sum(1 for c in cases if c.get("signals_required"))
    if n_sig < 5:
        errors.append(f"expected at least 5 signals_required scams, found {n_sig}")
    for c in cases:
        errors.extend(validate_case(c))
    return errors


def summary_table(cases):
    hdr = f"{'id':<6} {'outcome':<7} {'rail':<5} {'amount':>12} {'is_new':<6} {'mule':<5} {'sig_req':<7} {'steps':>5}  title"
    lines = [hdr, "-" * len(hdr)]
    for c in cases:
        p = c["payment"]
        b = p["beneficiary"]
        on_mule = b["account_ref"] in c["account_context"]["mule_list"]
        lines.append(
            f"{c['id']:<6} {c['expected']['outcome']:<7} {p['rail']:<5} "
            f"{p['amount_cents'] / 100:>12,.2f} {str(b['is_new']).lower():<6} "
            f"{str(on_mule).lower():<5} {str(c['signals_required']).lower():<7} "
            f"{c['expected']['max_friction_steps']:>5}  {c['title']}"
        )
    return "\n".join(lines)


def main(argv):
    cases_dir = argv[1] if len(argv) > 1 else CASES_DIR
    cases = load_cases(cases_dir)
    errors = validate_cases(cases)
    print(summary_table(cases))
    legit = [c for c in cases if c["id"].startswith("L-")]
    scams = [c for c in cases if c["id"].startswith("S-")]
    n_allow = sum(1 for c in legit if c["expected"]["outcome"] == "ALLOW")
    n_hold = sum(1 for c in legit if c["expected"]["outcome"] == "HOLD")
    n_deny = sum(1 for c in scams if c["expected"]["outcome"] == "DENY")
    n_sig = sum(1 for c in scams if c["signals_required"])
    n_empty = sum(1 for c in legit if not c["conversation"])
    exp_friction = sum(c["expected"]["max_friction_steps"] for c in legit) / max(len(legit), 1)
    print()
    print(f"cases: {len(cases)}  legit: {len(legit)} (ALLOW {n_allow}, HOLD {n_hold}, "
          f"empty-conversation {n_empty})  scams: {len(scams)} (HOLD {len(scams) - n_deny}, DENY {n_deny}, "
          f"signals_required {n_sig})")
    print(f"expected avg friction on legit if engine matches expectations: {exp_friction:.2f}")
    rails = {}
    for c in cases:
        rails[c["payment"]["rail"]] = rails.get(c["payment"]["rail"], 0) + 1
    print("rails:", ", ".join(f"{k} {v}" for k, v in sorted(rails.items())))
    if errors:
        print()
        print(f"{len(errors)} error(s):")
        for err in errors:
            print("  -", err)
        return 1
    print("schema OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
