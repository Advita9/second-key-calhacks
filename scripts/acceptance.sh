#!/usr/bin/env bash
# Acceptance gates G1..G8 from docs/ACCEPTANCE.md. Exit 0 only when everything passes.
# Thresholds here are fixed. Do not edit to pass.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
set -o pipefail
fail=0
pass() { echo "PASS  $1"; }
failm() { echo "FAIL  $1"; fail=1; }
have() { command -v "$1" >/dev/null 2>&1; }

# G1 kernel unit + property tests
if [ -d backend ] && have uv; then
  (cd backend && uv run --quiet pytest -q tests/unit -x 2>&1 | tail -3) && pass "G1 unit" || failm "G1 unit tests"
  (cd backend && HYPOTHESIS_PROFILE=ci uv run --quiet pytest -q tests/property -x 2>&1 | tail -3) && pass "G1 property" || failm "G1 property tests (ci profile)"
else
  failm "G1 backend/ missing or uv not installed"
fi

# G2 API flow tests
if [ -d backend/tests/api ]; then
  (cd backend && uv run --quiet pytest -q tests/api -x 2>&1 | tail -3) && pass "G2 api" || failm "G2 api tests"
else
  failm "G2 backend/tests/api missing"
fi

# G3 eval numbers
if [ -f scripts/eval.py ]; then
  (cd backend && MOCK_EXTRACTOR=1 uv run --quiet python ../scripts/eval.py --suite ../fixtures/cases --out ../eval/latest.json >/dev/null 2>&1) || failm "G3 eval.py did not run"
  if [ -f eval/latest.json ]; then
    python3 - <<'PY' && pass "G3 eval thresholds" || failm "G3 eval thresholds (unauthorized_releases must be 0, legit_completed >= 38, avg_friction_steps <= 2.0, 60 cases)"
import json, sys
r = json.load(open("eval/latest.json"))
ok = (r.get("unauthorized_releases") == 0 and r.get("legit_completed", 0) >= 38
      and r.get("avg_friction_steps", 9) <= 2.0 and r.get("legit_total") == 40 and r.get("scam_total") == 20)
print(json.dumps({k: r.get(k) for k in ["unauthorized_releases","legit_completed","legit_total","scam_total","avg_friction_steps","extractor_mode"]}))
sys.exit(0 if ok else 1)
PY
  else
    failm "G3 eval/latest.json missing"
  fi
else
  failm "G3 scripts/eval.py missing"
fi

# G4 room: spacetime module builds, and either e2e room test or recorded fallback decision
if [ -d spacetime ] && [ -f spacetime/package.json ]; then
  (cd spacetime && npm run --silent build >/dev/null 2>&1) && pass "G4 spacetime build" || failm "G4 spacetime module build"
else
  failm "G4 spacetime/ missing"
fi
if [ -x tests/e2e/test_room.sh ]; then
  tests/e2e/test_room.sh >/dev/null 2>&1 && pass "G4 room e2e" || failm "G4 room e2e (tests/e2e/test_room.sh)"
else
  failm "G4 tests/e2e/test_room.sh missing or not executable"
fi

# G5 frontend build + playwright smoke
if [ -d frontend ] && [ -f frontend/package.json ]; then
  (cd frontend && npm run --silent build >/dev/null 2>&1) && pass "G5 frontend build" || failm "G5 frontend build"
  if [ -f frontend/e2e/smoke.spec.ts ]; then
    (cd frontend && npx --yes playwright test e2e/smoke.spec.ts --reporter=line >/dev/null 2>&1) && pass "G5 playwright smoke" || failm "G5 playwright smoke"
  else
    failm "G5 frontend/e2e/smoke.spec.ts missing"
  fi
else
  failm "G5 frontend/ missing"
fi

# G6 voice tests
if [ -d backend/tests/voice ]; then
  (cd backend && uv run --quiet pytest -q tests/voice -x 2>&1 | tail -3) && pass "G6 voice" || failm "G6 voice tests"
else
  failm "G6 backend/tests/voice missing"
fi

# G7 demo mode under 60s
if [ -f scripts/demo.py ]; then
  start=$(date +%s)
  (cd backend && DEMO_MODE=1 uv run --quiet python ../scripts/demo.py >/dev/null 2>&1); rc=$?
  dur=$(( $(date +%s) - start ))
  if [ $rc -eq 0 ] && [ $dur -le 60 ]; then pass "G7 demo.py (${dur}s)"; else failm "G7 demo.py rc=$rc ${dur}s"; fi
else
  failm "G7 scripts/demo.py missing"
fi

# G8 docs
for f in README.md docs/MORNING.md docs/DEVPOST_DRAFT.md docs/DECISIONS.md; do
  [ -s "$f" ] && pass "G8 $f" || failm "G8 $f missing or empty"
done
# writing rules scan on public docs and UI copy
if grep -rniE "accenture|\bABG\b|tamper-proof|tamper proof|physically cannot|speaker (id|identification)|—" README.md docs/DEVPOST_DRAFT.md frontend/src 2>/dev/null | grep -v node_modules | head -5; then
  failm "G8 writing rules violated (see lines above)"
else
  pass "G8 writing rules"
fi
# STATUS gates all checked
if [ -f docs/STATUS.md ] && ! grep -qE "^- \[ \] G[1-8]" docs/STATUS.md; then pass "G8 STATUS gates checked"; else failm "G8 docs/STATUS.md still has unchecked gates"; fi

echo
if [ $fail -eq 0 ]; then echo "ACCEPTANCE: GREEN"; else echo "ACCEPTANCE: RED"; fi
exit $fail
