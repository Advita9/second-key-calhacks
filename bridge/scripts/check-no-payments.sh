#!/usr/bin/env bash
# Guard: the bridge has no code path to money. Its hand-written sources must
# never mention the kernel payment routes. Generated bindings are excluded
# because the scoreboard column `unauthorized_releases` contains the word.
set -u
cd "$(dirname "$0")/.."
hits="$(grep -rn --include='*.ts' -e '/payments' -e 'release' src --exclude-dir=module_bindings || true)"
if [ -n "$hits" ]; then
  echo "bridge/src mentions a payment route or word:" >&2
  echo "$hits" >&2
  exit 1
fi
echo "ok: bridge/src has no /payments or release mentions"
