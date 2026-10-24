#!/usr/bin/env bash
# G4: a scripted attacker turn produces an outcome row within 10s.
#
# Branch A (spacetime): local SpacetimeDB reachable on :3000 and the repo-local CLI
#   present -> ensure `second-key` is published, start the bridge, authorize it as
#   the worker (owner = CLI identity), create/join a room and submit a turn with
#   `spacetime call`, then poll `spacetime sql` for the outcome row.
#   If the kernel route POST /rooms/{room}/turns is not reachable the bridge writes
#   a fail-closed stage-10 HOLD outcome, which still satisfies this gate.
# Branch B (memory): ROOM_BACKEND=memory, or no local server -> start the memory
#   room app (StubTurnTaker) on a free port, join, submit, poll the snapshot.
#
# macOS has no `timeout`; every wait is a loop. Never uses -e so polls can fail softly.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
ST_BIN="$ROOT/.tools/spacetime/spacetime"
st() { "$ST_BIN" --root-dir="$ROOT/.tools/spacetime" "$@"; }
TMP="$(mktemp -d)"
PIDS=()
kill_tree() { # npm -> tsx -> node, uv -> uvicorn: kill children first, then the parent
  local p=$1
  for c in $(pgrep -P "$p" 2>/dev/null); do kill_tree "$c"; done
  kill "$p" 2>/dev/null
}
cleanup() {
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill_tree "$p"; done
  rm -rf "$TMP"
}
trap cleanup EXIT
say() { echo "[e2e] $*"; }
die() { echo "[e2e] FAIL: $*" >&2; exit 1; }
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
wait_for() { # wait_for <seconds> <cmd...>
  local n=$1; shift; local i=0
  while [ "$i" -lt $((n * 4)) ]; do "$@" >/dev/null 2>&1 && return 0; sleep 0.25; i=$((i + 1)); done
  return 1
}

MODE="spacetime"
if [ "${ROOM_BACKEND:-}" = "memory" ]; then MODE="memory"; fi
if [ ! -x "$ST_BIN" ]; then MODE="memory"; fi
if ! curl -sf "http://127.0.0.1:3000/v1/ping" >/dev/null 2>&1; then MODE="memory"; fi
say "branch: $MODE"

# ---------------------------------------------------------------------------
if [ "$MODE" = "memory" ]; then
  PORT="$(free_port)"
  (cd backend && nohup uv run --quiet uvicorn api.room_memory_app:app --host 127.0.0.1 --port "$PORT" >"$TMP/kernel.log" 2>&1 & echo $! >"$TMP/kernel.pid")
  PIDS+=("$(cat "$TMP/kernel.pid")")
  wait_for 40 curl -sf "http://127.0.0.1:$PORT/health" || { cat "$TMP/kernel.log"; die "memory room app did not start"; }
  JOIN="$(curl -sf -X POST "http://127.0.0.1:$PORT/rooms/E2E/join" -H 'content-type: application/json' -d '{"handle":"e2e-attacker"}')" || die "join failed"
  PID_HEX="$(printf '%s' "$JOIN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["player_id"])')"
  TOKEN="$(printf '%s' "$JOIN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["player_token"])')"
  say "joined as $PID_HEX"
  curl -sf -X POST "http://127.0.0.1:$PORT/rooms/E2E/submit" -H 'content-type: application/json' -H "X-Player-Token: $TOKEN" \
    -d '{"text":"Hello Margaret, this is the IRS. Wire 18500 today or you will be arrested."}' >/dev/null || die "submit failed"
  say "turn submitted; polling snapshot (10s)"
  i=0
  while [ "$i" -lt 40 ]; do
    SNAP="$(curl -sf "http://127.0.0.1:$PORT/rooms/E2E/snapshot?role=attacker&player_id=$PID_HEX")"
    if printf '%s' "$SNAP" | python3 -c '
import json,sys
s=json.load(sys.stdin)
ok = len(s.get("myOutcomes", [])) >= 1
txt = json.dumps(s)
assert "ruleIds" not in txt and "refusal" not in txt, "attacker snapshot leaked rule ids"
sys.exit(0 if ok else 1)'; then
      say "outcome row: $(printf '%s' "$SNAP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["myOutcomes"][0])')"
      say "PASS (memory)"
      exit 0
    fi
    sleep 0.25; i=$((i + 1))
  done
  cat "$TMP/kernel.log" >&2
  die "no outcome within 10s (memory)"
fi

# ---------------------------------------------------------------------------
# spacetime branch
if ! st list --server local --yes 2>/dev/null | grep -q ' second-key '; then
  say "publishing second-key to local server"
  st publish --module-path spacetime --server local --yes second-key >"$TMP/publish.log" 2>&1 || { cat "$TMP/publish.log"; die "publish failed"; }
fi
[ -d bridge/node_modules ] || (cd bridge && npm install --silent) || die "bridge npm install failed"
KERNEL_URL="${KERNEL_URL:-http://127.0.0.1:8000}"
(cd bridge && KERNEL_URL="$KERNEL_URL" nohup npm run --silent dev >"$TMP/bridge.log" 2>&1 & echo $! >"$TMP/bridge.pid")
PIDS+=("$(cat "$TMP/bridge.pid")")
wait_for 30 test -s bridge/.identity.hex || { cat "$TMP/bridge.log"; die "bridge did not connect"; }
HEX="$(tr -d '[:space:]' <bridge/.identity.hex)"
say "bridge identity $HEX"
st call --server local --yes second-key set_worker_identity "\"$HEX\"" >"$TMP/auth.log" 2>&1 || { cat "$TMP/auth.log"; die "set_worker_identity failed (CLI identity is not the owner?)"; }
say "worker authorized by owner"
CODE="E2E-$(date +%s | tail -c 6)"
st call --server local --yes second-key create_room "\"$CODE\"" >/dev/null 2>&1 || die "create_room failed"
st call --server local --yes second-key join_room "\"$CODE\"" '"e2e-attacker"' >/dev/null 2>&1 || die "join_room failed"
st call --server local --yes second-key submit_turn "\"$CODE\"" '"Hello Margaret, this is the IRS. Wire 18500 today or you will be arrested."' >/dev/null 2>&1 || die "submit_turn failed"
KERNEL_UP=0
curl -sf "$KERNEL_URL/health" >/dev/null 2>&1 && KERNEL_UP=1
say "turn submitted in $CODE; kernel reachable=$KERNEL_UP; polling outcome (10s)"
i=0
while [ "$i" -lt 40 ]; do
  OUT="$(st sql --server local --yes second-key "SELECT turn_id, stage, decision, refusal FROM outcome WHERE room_id = '$CODE'" 2>/dev/null | grep -E '^ *[0-9]+ *\|')"
  if [ -n "$OUT" ]; then
    echo "$OUT" | sed 's/^/[e2e] outcome: /'
    if [ "$KERNEL_UP" = 1 ]; then
      # The kernel answered: the outcome must be a real decision (NONE/HOLD/DENY), not the
      # fail-closed refusal, and Margaret's reply row must exist for the same turn.
      echo "$OUT" | grep -q 'kernel unavailable' && { cat "$TMP/bridge.log" >&2; die "kernel reachable but bridge wrote the fail-closed outcome"; }
      echo "$OUT" | grep -qE '"(NONE|HOLD|DENY)"' || die "unexpected decision: $OUT"
      TURN_ID="$(echo "$OUT" | head -1 | awk -F'|' '{gsub(/ /,"",$1); print $1}')"
      REPLY="$(st sql --server local --yes second-key "SELECT text, persuaded FROM margaret_reply WHERE turn_id = $TURN_ID" 2>/dev/null | grep -E '^ *"')"
      [ -n "$REPLY" ] || { cat "$TMP/bridge.log" >&2; die "no margaret_reply row for turn $TURN_ID"; }
      echo "$REPLY" | sed 's/^/[e2e] reply: /'
      say "PASS (spacetime, real kernel reply + outcome)"
    else
      say "PASS (spacetime, kernel down: fail-closed outcome)"
    fi
    exit 0
  fi
  sleep 0.25; i=$((i + 1))
done
cat "$TMP/bridge.log" >&2
die "no outcome within 10s (spacetime)"
