#!/usr/bin/env bash
# Stop gate. Claude is not allowed to stop until scripts/acceptance.sh passes,
# or the hard stop time is reached, or the iteration cap is hit, or .claude/STOP_NOW exists.
# Exit 0 with no JSON = allow stop. JSON {"decision":"block","reason":...} = keep working.

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
HARD_STOP="${OVERNIGHT_HARD_STOP:-07:30}"     # local time, HH:MM
MAX_ITER="${OVERNIGHT_MAX_ITER:-60}"
COUNT_FILE="$ROOT/.claude/.overnight_iter"
LOG="$ROOT/.claude/overnight.log"

input="$(cat)"   # hook JSON on stdin (has stop_hook_active); kept for the log

# Kill switch
if [ -f "$ROOT/.claude/STOP_NOW" ]; then
  echo "$(date '+%F %T') STOP_NOW present, allowing stop" >> "$LOG"
  exit 0
fi

# Hard stop window (morning)
now="$(date +%H:%M)"
if [[ "$now" > "$HARD_STOP" && "$now" < "12:00" ]]; then
  echo "$(date '+%F %T') hard stop $HARD_STOP reached, allowing stop" >> "$LOG"
  exit 0
fi

# Iteration cap
n="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
n=$((n + 1))
echo "$n" > "$COUNT_FILE"
if [ "$n" -gt "$MAX_ITER" ]; then
  echo "$(date '+%F %T') iteration cap $MAX_ITER reached, allowing stop" >> "$LOG"
  exit 0
fi

# Acceptance
out="$(bash "$ROOT/scripts/acceptance.sh" 2>&1)"
rc=$?
echo "$(date '+%F %T') iter=$n acceptance_rc=$rc" >> "$LOG"
if [ $rc -eq 0 ]; then
  exit 0
fi

OUT="$out" N="$n" python3 - <<'PY'
import json, os
out = os.environ["OUT"][-3500:]
n = os.environ["N"]
reason = (
    f"Acceptance is not green (stop-gate iteration {n}). Do not stop.\n"
    "1. Open docs/STATUS.md, set Iteration, pick the first unchecked build-order item that the failing gate needs.\n"
    "2. Use the subagent pattern: architect -> engineer -> invariant-reviewer -> red-team (kernel) -> eval-engineer. Commit when green.\n"
    "3. Update docs/STATUS.md. If a human is required, write it under 'Blocked for Armaan', mock around it, continue.\n"
    "4. Never edit docs/ACCEPTANCE.md or scripts/acceptance.sh to pass.\n\n"
    "acceptance.sh output (tail):\n" + out
)
print(json.dumps({"decision": "block", "reason": reason}))
PY
exit 0
