#!/usr/bin/env bash
# usage: ./scripts/setkey.sh ANTHROPIC_API_KEY   (then paste the key, press Enter; input is hidden)
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] || cp .env.example .env
name="$1"; [ -z "$name" ] && { echo "usage: $0 VAR_NAME"; exit 1; }
printf "Paste %s and press Enter (hidden): " "$name"
read -rs val; echo
[ -z "$val" ] && { echo "empty, nothing changed"; exit 1; }
LC_ALL=C sed -i '' "s|^$name=.*|$name=$val|" .env
grep -q "^$name=$val" .env || echo "$name=$val" >> .env
case "$name" in CARTESIA_API_KEY) LC_ALL=C sed -i '' 's|^TTS_PROVIDER=.*|TTS_PROVIDER=cartesia|; s|^STT_PROVIDER=.*|STT_PROVIDER=cartesia|' .env;; esac
echo "$name set (${#val} chars)"
