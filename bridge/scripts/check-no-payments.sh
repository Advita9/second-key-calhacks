#!/usr/bin/env bash
# Guard: the bridge has no code path to money. Its hand-written sources must
# never mention a payment sub-route (/payments/{id}/attest, /certificate, ...)
# or the word "release". The only allowed mention of /payments is the read-only
# GET of the list in kernel.ts; every line that mentions it must say GET.
# Generated bindings are excluded (the scoreboard column is `unauthorized_releases`).
set -u
cd "$(dirname "$0")/.."
hits="$(grep -rn --include='*.ts' -e '/payments/' -e 'release' src --exclude-dir=module_bindings || true)"
if [ -n "$hits" ]; then
  echo "bridge/src mentions a payment sub-route or the forbidden word:" >&2
  echo "$hits" >&2
  exit 1
fi
bad="$(grep -rn --include='*.ts' '/payments' src --exclude-dir=module_bindings | grep -v 'GET' || true)"
if [ -n "$bad" ]; then
  echo "bridge/src mentions /payments on a line that is not marked GET:" >&2
  echo "$bad" >&2
  exit 1
fi
files="$(grep -rln --include='*.ts' '/payments' src --exclude-dir=module_bindings || true)"
for f in $files; do
  if [ "$f" != "src/kernel.ts" ]; then
    echo "only src/kernel.ts may reference /payments (found in $f)" >&2
    exit 1
  fi
done
if grep -n "'POST'" src/kernel.ts | grep -q payments; then
  echo "kernel.ts must never POST to /payments" >&2
  exit 1
fi
echo "ok: bridge/src never mutates payments and never mentions release"
