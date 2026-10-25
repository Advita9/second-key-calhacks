#!/usr/bin/env bash
# Start, stop or inspect the local dev stack.
#   scripts/dev.sh start [--fresh]   kernel :8000 (--fresh deletes the SQLite db and its audit anchor sidecar first),, SpacetimeDB :3000 (if ROOM_BACKEND=spacetime), bridge, frontend :3001
#   scripts/dev.sh stop
#   scripts/dev.sh status
# Everything is logged under .claude/*.log and tracked by .claude/*.pid.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PID_DIR="$ROOT/.claude"
mkdir -p "$PID_DIR"

# SpacetimeDB CLI is repo-local (see docs/DECISIONS.md). Always invoke through this wrapper.
SPACETIME_BIN="$ROOT/.tools/spacetime/spacetime"
spacetime_cli() { "$SPACETIME_BIN" --root-dir="$ROOT/.tools/spacetime" "$@"; }

load_env() {
  if [ -f "$ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in ''|'#'*) continue ;; esac
      line="${line%%#*}"                         # strip trailing comments
      line="${line%"${line##*[![:space:]]}"}"    # rtrim
      [ -z "$line" ] && continue
      export "$line"
    done < "$ROOT/.env"
  fi
}

stop_one() {
  local pidfile="$1" name="$2"
  if [ -f "$pidfile" ]; then
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
      echo "stopped $name (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
}

wait_http() {  # wait_http <url> <seconds>
  local url="$1" secs="${2:-30}" i=0
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    i=$((i+1)); [ "$i" -ge $((secs*2)) ] && return 1; sleep 0.5
  done
}

start_kernel() {
  (cd "$ROOT/backend" && uv sync --quiet)
  stop_one "$PID_DIR/kernel.pid" kernel
  # Run uvicorn from the venv directly so .claude/kernel.pid is uvicorn's own pid (kill-able for the fail-closed test).
  (cd "$ROOT/backend" && nohup "$ROOT/backend/.venv/bin/python" -m uvicorn api.main:app --host 0.0.0.0 --port 8000 \
      >"$PID_DIR/kernel.log" 2>&1 & echo $! >"$PID_DIR/kernel.pid")
  wait_http http://127.0.0.1:8000/health 60 || { echo "kernel did not come up; see $PID_DIR/kernel.log" >&2; exit 1; }
  echo "kernel      http://127.0.0.1:8000/health      log: .claude/kernel.log"
  local health; health="$(curl -s http://127.0.0.1:8000/health)"; echo "$health"
  if printf '%s' "$health" | grep -q '"anchor": *"mismatch"'; then
    echo
    echo "WARNING     the audit anchor does not match the database (an old database, or rows changed while the kernel was down)."
    echo "            Payments are refused until you either start fresh:   scripts/dev.sh start --fresh"
    echo "            or acknowledge it as the operator:   curl -s -X POST -H \"X-Ops-Token: $OPS_TOKEN\" http://127.0.0.1:8000/audit/acknowledge"
    echo
  fi
}

start_spacetime() {
  if ! curl -fsS -o /dev/null http://127.0.0.1:3000/v1/ping 2>/dev/null; then
    [ -x "$SPACETIME_BIN" ] || { echo "spacetime CLI missing at $SPACETIME_BIN (see docs/DECISIONS.md); set ROOM_BACKEND=memory" >&2; exit 1; }
    (nohup "$SPACETIME_BIN" --root-dir="$ROOT/.tools/spacetime" start >"$PID_DIR/spacetime.log" 2>&1 & echo $! >"$PID_DIR/spacetime.pid")
    wait_http http://127.0.0.1:3000/v1/ping 60 || { echo "SpacetimeDB did not come up; see $PID_DIR/spacetime.log" >&2; exit 1; }
  fi
  echo "spacetimedb http://127.0.0.1:3000             log: .claude/spacetime.log"
  spacetime_cli publish --module-path spacetime --server local --yes "${SPACETIME_DB:-second-key}" >"$PID_DIR/publish.log" 2>&1 \
    || { echo "publish failed; see $PID_DIR/publish.log" >&2; exit 1; }
  echo "module      published as ${SPACETIME_DB:-second-key} (log: .claude/publish.log)"
  # Create the demo room (caller = CLI identity becomes the room operator). Already-exists errors are fine.
  spacetime_cli call --server local --yes "${SPACETIME_DB:-second-key}" create_room "\"${ROOM_CODE:-DEMO}\"" >>"$PID_DIR/publish.log" 2>&1 \
    && echo "room        ${ROOM_CODE:-DEMO} created" || echo "room        ${ROOM_CODE:-DEMO} already exists (or create_room failed; see .claude/publish.log)"
}

start_bridge() {
  stop_one "$PID_DIR/bridge.pid" bridge
  [ -d "$ROOT/bridge/node_modules" ] || (cd "$ROOT/bridge" && npm install --silent)
  (cd "$ROOT/bridge" && KERNEL_URL=http://127.0.0.1:8000 SPACETIME_URI="${SPACETIME_URI:-ws://127.0.0.1:3000}" \
      SPACETIME_DB="${SPACETIME_DB:-second-key}" nohup npm run dev >"$PID_DIR/bridge.log" 2>&1 & echo $! >"$PID_DIR/bridge.pid")
  local i=0
  until [ -s "$ROOT/bridge/.identity.hex" ] || [ $i -ge 60 ]; do sleep 0.5; i=$((i+1)); done
  if [ -s "$ROOT/bridge/.identity.hex" ]; then
    spacetime_cli call --server local --yes "${SPACETIME_DB:-second-key}" set_worker_identity "\"$(cat "$ROOT/bridge/.identity.hex")\"" \
      >>"$PID_DIR/publish.log" 2>&1 && echo "worker      authorized identity $(cut -c1-12 "$ROOT/bridge/.identity.hex")..." \
      || echo "worker      set_worker_identity failed (already set, or not owner); see .claude/publish.log"
  else
    echo "bridge      did not report an identity in 30s; see .claude/bridge.log" >&2
  fi
  echo "bridge      log: .claude/bridge.log"
}

start_frontend() {
  if curl -fsS -o /dev/null http://127.0.0.1:3001/board 2>/dev/null && [ -f "$PID_DIR/frontend.pid" ] && kill -0 "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null; then
    echo "frontend    already running on :3001 (left as is)"; return 0
  fi
  stop_one "$PID_DIR/frontend.pid" frontend
  [ -d "$ROOT/final-frontend/node_modules" ] || (cd "$ROOT/final-frontend" && npm install --silent)
  (
    cd "$ROOT/final-frontend"
    NEXT_PUBLIC_ROOM_BACKEND="${ROOM_BACKEND:-spacetime}" \
    NEXT_PUBLIC_HAS_BINDINGS=1 \
    NEXT_PUBLIC_SPACETIME_URI="${SPACETIME_URI:-ws://127.0.0.1:3000}" \
    NEXT_PUBLIC_SPACETIME_DB="${SPACETIME_DB:-second-key}" \
    nohup npm run dev -- -p 3001 -H 0.0.0.0 >"$PID_DIR/frontend.log" 2>&1 &
    echo $! >"$PID_DIR/frontend.pid"
  )
  wait_http http://127.0.0.1:3001/board 120 || echo "frontend slow to start; see .claude/frontend.log"
  echo "frontend    http://localhost:3001/board  /play  /ops   log: .claude/frontend.log"
}
prerender_audio() {
  (cd "$ROOT/backend" && nohup uv run python ../scripts/prerender_audio.py >"$PID_DIR/prerender.log" 2>&1 &)
  echo "audio       pre-rendering Margaret's lines in the background (TTS_PROVIDER=${TTS_PROVIDER:-mock}); log: .claude/prerender.log"
}

cmd="${1:-start}"
case "$cmd" in
  stop)
    stop_one "$PID_DIR/frontend.pid" frontend
    stop_one "$PID_DIR/bridge.pid" bridge
    stop_one "$PID_DIR/kernel.pid" kernel
    stop_one "$PID_DIR/spacetime.pid" spacetimedb
    exit 0
    ;;
  status)
    load_env
    echo "kernel:      $(curl -s http://127.0.0.1:8000/health || echo down)"
    echo "spacetimedb: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/v1/ping || echo down)"
    echo "frontend:    $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/board || echo down)"
    [ -f "$PID_DIR/bridge.pid" ] && kill -0 "$(cat "$PID_DIR/bridge.pid")" 2>/dev/null && echo "bridge:      running" || echo "bridge:      down"
    exit 0
    ;;
  start)
    load_env
    if [ "${2:-}" = "--fresh" ]; then
      rm -f "$ROOT/backend/second_key.db" "$ROOT/backend/second_key.db.head.json" "$ROOT/backend/second_key.db-wal" "$ROOT/backend/second_key.db-shm"
      echo "fresh       removed backend/second_key.db and its audit anchor sidecar"
    fi
    if [ -z "${OPS_TOKEN:-}" ]; then
      OPS_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"; export OPS_TOKEN
      echo "OPS_TOKEN not in .env; generated one for this run (add OPS_TOKEN=$OPS_TOKEN to .env to keep it)."
    fi
    [ "${DEMO_MODE:-0}" = "1" ] || echo "note        DEMO_MODE is not 1 in .env: the mutate attack and the tamper button will be off (set DEMO_MODE=1 for the table demo)"
    start_kernel
    if [ "${ROOM_BACKEND:-spacetime}" = "spacetime" ]; then
      start_spacetime
      start_bridge
    else
      echo "room        memory backend (ROOM_BACKEND=memory); no SpacetimeDB, no bridge"
    fi
    prerender_audio
    start_frontend
    LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || echo "<laptop-ip>")"
    echo
    echo "ops token:  $OPS_TOKEN"
    echo "board:      http://localhost:3001/board?room=DEMO&token=$OPS_TOKEN   (projector; token unlocks the attack panel)"
    echo "ops:        http://localhost:3001/ops?token=$OPS_TOKEN"
    echo "phones:     http://$LAN_IP:3001/play?room=DEMO   (never share the token URL with players)"
    echo "stop with:  scripts/dev.sh stop"
    ;;
  *)
    echo "usage: $0 [start [--fresh]|stop|status]" >&2; exit 2 ;;
esac
