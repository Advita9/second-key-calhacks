#!/usr/bin/env bash
# Start the overnight session. Run inside tmux so it survives a closed terminal:
#   tmux new -s overnight
#   ./scripts/overnight.sh
# Detach with Ctrl-b d. Reattach with: tmux attach -t overnight
# Kill switch (lets Claude stop at its next natural pause): touch .claude/STOP_NOW
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

MODEL="${MODEL:-fable}"                 # alias or full id, e.g. claude-fable-5-1
export OVERNIGHT_HARD_STOP="${OVERNIGHT_HARD_STOP:-07:30}"
export OVERNIGHT_MAX_ITER="${OVERNIGHT_MAX_ITER:-60}"

# Never let the shell leak the product API key into Claude Code billing.
unset ANTHROPIC_API_KEY

rm -f .claude/STOP_NOW .claude/.overnight_iter
chmod +x .claude/hooks/*.sh scripts/*.sh 2>/dev/null
mkdir -p eval

echo "model=$MODEL hard_stop=$OVERNIGHT_HARD_STOP max_iter=$OVERNIGHT_MAX_ITER"
echo "log: .claude/overnight.log   status: docs/STATUS.md"
echo

# -d no display sleep, -i no idle sleep, -m no disk sleep, -s no system sleep on AC, -u user active
exec caffeinate -dimsu claude \
  --model "$MODEL" \
  --dangerously-skip-permissions \
  "$(cat PROMPT.md)"
