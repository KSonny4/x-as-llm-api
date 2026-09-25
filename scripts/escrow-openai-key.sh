#!/usr/bin/env bash
# escrow-openai-key.sh — self-serve escrow of an OpenAI key into Bao.
#
# The key flows: your terminal -> Bao ONLY. Never git, never logs, never argv.
# Usage:
#   export BAO_ADDR=https://secrets.pkubelka.cz
#   bash scripts/escrow-openai-key.sh            # prompts silently
#   OPENAI_API_KEY=sk-... OWNER_EMAIL=you@x bash scripts/escrow-openai-key.sh
#
# Result: secret/projects/pi-infinity-llm/OPENAI_API_KEY {key,email,status}
# (the exact shape scripts/render-seeds.sh expects: d.key or d.access,
# d.email, d.status; active unless disabled/retired/inactive/revoked/banned).
# Next (operator, separate step): add the emit line to render-seeds.sh,
# re-render seeds, redeploy keeper. See the post-run echo.
set -euo pipefail

ENTRY="secret/projects/pi-infinity-llm/OPENAI_API_KEY"
export BAO_ADDR="${BAO_ADDR:?BAO_ADDR required (e.g. https://secrets.pkubelka.cz)}"

KEY="${OPENAI_API_KEY:-}"
if [ -z "$KEY" ]; then
  printf 'OpenAI API key (silent): ' >&2
  stty -echo 2>/dev/null || true
  IFS= read -r KEY
  stty echo 2>/dev/null || true
  echo >&2
fi
[ -n "$KEY" ] || { echo "EMPTY-KEY abort" >&2; exit 1; }
case "$KEY" in sk-*) ;; *) echo "WARN: key does not start with sk- (continuing)" >&2;; esac

EMAIL="${OWNER_EMAIL:-}"
if [ -z "$EMAIL" ]; then
  printf 'Owner email (for Bao metadata): ' >&2
  IFS= read -r EMAIL
fi
[ -n "$EMAIL" ] || { echo "EMPTY-EMAIL abort" >&2; exit 1; }

if bao kv get -format=json "$ENTRY" >/dev/null 2>&1; then
  if [ "${OVERWRITE:-0}" != "1" ]; then
    echo "ENTRY-EXISTS abort (set OVERWRITE=1 to replace)" >&2
    unset KEY EMAIL; exit 1
  fi
  echo "overwriting existing entry (OVERWRITE=1)" >&2
fi

# Via stdin? bao kv put takes k=v args; env-sourced, never argv-typed key:
# the value travels process-local only. Lengths on stdout, never the value.
printf '%s' "$KEY" | bao kv put "$ENTRY" key="-" email="$EMAIL" status="active" >/dev/null
unset KEY
VER="$(bao kv get -format=json "$ENTRY" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['metadata']['version'])")"
echo "escrowed: $ENTRY v$VER (key_len_hidden, email=$EMAIL, status=active)" >&2
unset EMAIL VER

cat >&2 <<'EOF'

Next (keeper operator):
  1. Add to scripts/render-seeds.sh live-wire section:
       emit OPENAI_API_KEY openai "gpt-6-luna" "https://api.openai.com/v1" openai "openai/gpt-6-luna" "GPT-6 Luna via OpenAI" 1
  2. bash scripts/render-seeds.sh > /tmp/seeds-live.json   # values to file, deploy-only
  3. Redeploy keeper with -var=seeds_json="$(cat /tmp/seeds-live.json)" (see keeper.nomad.hcl header)
  4. shred -u /tmp/seeds-live.json
  5. Acceptance: structured-output chat -> 200 (was 503 no_working_compatible_free_model)
EOF
echo "ESCROW-OK"
