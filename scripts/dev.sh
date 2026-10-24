#!/usr/bin/env bash
# Start (or stop) the local dev stack. Usage: scripts/dev.sh [start|stop]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PID_DIR="$ROOT/.claude"
KERNEL_PID="$PID_DIR/kernel.pid"
KERNEL_LOG="$PID_DIR/kernel.log"
mkdir -p "$PID_DIR"

# SpacetimeDB CLI is repo-local (see docs/DECISIONS.md). Always invoke through this wrapper.
SPACETIME_BIN="$ROOT/.tools/spacetime/spacetime"
spacetime_cli() { "$SPACETIME_BIN" --root-dir="$ROOT/.tools/spacetime" "$@"; }

load_env() {
  if [ -f "$ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in ''|'#'*) continue ;; esac
      line="${line%%#*}"           # strip trailing comments
      line="${line%"${line##*[![:space:]]}"}"  # rtrim
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
      kill "$pid" 2>/dev/null || true
      echo "stopped $name (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
}

cmd="${1:-start}"
case "$cmd" in
  stop)
    stop_one "$KERNEL_PID" kernel
    # TODO(item 9): stop spacetime + bridge.  TODO(item 10): stop frontend.
    exit 0
    ;;
  start)
    load_env
    (cd "$ROOT/backend" && uv sync --quiet)
    stop_one "$KERNEL_PID" kernel
    (cd "$ROOT/backend" && nohup uv run uvicorn api.main:app --host 127.0.0.1 --port 8000 \
        >"$KERNEL_LOG" 2>&1 & echo $! >"$KERNEL_PID")
    echo "kernel     http://127.0.0.1:8000/health   (log: $KERNEL_LOG)"
    # TODO(item 9): start SpacetimeDB:  spacetime_cli start  (then publish module from spacetime/)
    # TODO(item 9): start bridge:       (cd bridge && npm run dev)
    # TODO(item 10): start frontend:    (cd frontend && npm run dev)   -> http://localhost:3000/board
    echo "stop with: scripts/dev.sh stop"
    ;;
  *)
    echo "usage: $0 [start|stop]" >&2; exit 2 ;;
esac
