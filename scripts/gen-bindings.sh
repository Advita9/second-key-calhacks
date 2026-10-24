#!/usr/bin/env bash
# Regenerate SpacetimeDB TypeScript bindings for the bridge and the frontend.
# Bindings are committed, so builds never need the CLI. Run after editing
# spacetime/src/index.ts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SPACETIME_BIN="$ROOT/.tools/spacetime/spacetime"
if [ ! -x "$SPACETIME_BIN" ]; then
  echo "spacetime CLI not found at $SPACETIME_BIN (see docs/DECISIONS.md)" >&2
  exit 1
fi
st() { "$SPACETIME_BIN" --root-dir="$ROOT/.tools/spacetime" "$@"; }
mkdir -p "$ROOT/frontend/src"
for out in bridge/src/module_bindings frontend/src/module_bindings; do
  rm -rf "$ROOT/$out"
  st generate --lang typescript --out-dir "$ROOT/$out" --module-path "$ROOT/spacetime" --yes
  echo "generated $out"
done
