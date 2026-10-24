#!/usr/bin/env bash
# Run this before overnight.sh. Tells you what is missing. Does not install anything.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
ok=1
chk() { if command -v "$1" >/dev/null 2>&1; then echo "ok    $1 $($1 --version 2>/dev/null | head -1)"; else echo "MISS  $1   -> $2"; ok=0; fi; }

echo "== tools"
chk claude   "npm i -g @anthropic-ai/claude-code   (or: claude update)"
chk node     "brew install node"
chk npm      "comes with node"
chk python3  "brew install python@3.12"
chk uv       "brew install uv"
chk git      "xcode-select --install"
chk tmux     "brew install tmux"
chk caffeinate "built into macOS"
chk say      "built into macOS (MockTTS)"
if command -v spacetime >/dev/null 2>&1; then echo "ok    spacetime $(spacetime --version 2>/dev/null | head -1)"; else echo "opt   spacetime  -> curl -sSf https://install.spacetimedb.com | sh   (agent will try; fallback exists)"; fi

echo "== keys (.env)"
if [ -f .env ]; then
  for k in ANTHROPIC_API_KEY CARTESIA_API_KEY NESSIE_API_KEY; do
    if grep -qE "^$k=.+" .env; then echo "ok    $k"; else echo "opt   $k   (mock will be used)"; fi
  done
  grep -qE "^PUSH_OK=1" .env && echo "ok    PUSH_OK=1 (agent may git push to origin)" || echo "info  PUSH_OK not set (agent commits locally only)"
else
  echo "MISS  .env  -> cp .env.example .env and fill what you have"; ok=0
fi
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "WARN  ANTHROPIC_API_KEY is exported in this shell. Claude Code will bill the API instead of your subscription. Run: unset ANTHROPIC_API_KEY"
fi

echo "== repo"
if [ -d .git ]; then echo "ok    git repo"; git remote -v | head -2; else echo "MISS  git init  -> git init && git add -A && git commit -m 'kit'"; ok=0; fi

echo "== hooks executable"
for f in .claude/hooks/stop-gate.sh .claude/hooks/post-edit.sh scripts/acceptance.sh; do
  [ -x "$f" ] && echo "ok    $f" || { echo "FIX   chmod +x $f"; chmod +x "$f" && echo "      fixed"; }
done

echo "== power"
pmset -g batt 2>/dev/null | head -1
echo "Keep the lid open and the charger in. overnight.sh wraps Claude in caffeinate."

echo
[ $ok -eq 1 ] && echo "PREFLIGHT: ready" || echo "PREFLIGHT: fix MISS lines first"
