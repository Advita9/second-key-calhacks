#!/usr/bin/env bash
# After Edit/Write: lint Python files in backend/ with ruff. Exit 2 shows stderr to Claude.
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
input="$(cat)"
file="$(printf '%s' "$input" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null)"
[ -z "$file" ] && exit 0

case "$file" in
  *"/backend/"*.py)
    if [ -d "$ROOT/backend" ] && command -v uv >/dev/null 2>&1; then
      cd "$ROOT/backend" || exit 0
      if ! uv run --quiet ruff check "$file" 2>&1 | head -40 >&2; then
        exit 2
      fi
      uv run --quiet ruff format "$file" >/dev/null 2>&1 || true
    fi
    ;;
  *"/docs/ACCEPTANCE.md"|*"/scripts/acceptance.sh")
    echo "You edited an acceptance gate. CLAUDE.md forbids lowering thresholds. Revert unless this is a fix to a broken check, and record the reason in docs/DECISIONS.md." >&2
    exit 2
    ;;
esac
exit 0
