#!/usr/bin/env bash
# render-keyround-keys.sh — emit the key pool as JSON [{name, value}].
# Values flow Bao -> stdout ONLY (captured into -var at register time).
# NOTHING secret is stored: names are public, values deploy-only.
# Usage: KEYS_JSON="$(bash scripts/render-keyround-keys.sh)"
set -u
PREFIX="secret/projects/pi-infinity-llm"
first=1
echo -n "["
for k in OPENCODE_ZEN_API_KEY OPENCODE_ZEN_API_KEY_PETR \
  OPENCODE_ZEN_RETIRED_1 OPENCODE_ZEN_RETIRED_2 OPENCODE_ZEN_RETIRED_3 \
  OPENCODE_ZEN_RETIRED_4 OPENCODE_ZEN_RETIRED_5 OPENCODE_ZEN_RETIRED_6 \
  OPENCODE_ZEN_RETIRED_7 OPENCODE_ZEN_RETIRED_8; do
  v="$(bao kv get -format=json "$PREFIX/$k" 2>/dev/null | python3 -c \
    "import json,sys; d=json.load(sys.stdin)['data']['data']; print(d.get('key') or d.get('access') or '')")"
  [ -n "$v" ] || { echo "no value: $k" >&2; continue; }
  [ $first = 1 ] || echo -n ","
  first=0
  python3 - "$k" "$v" <<'EOF'
import json, sys
print(json.dumps({"name": sys.argv[1], "value": sys.argv[2]}), end="")
EOF
done
echo "]"
