#!/usr/bin/env bash
# render-seeds.sh — render keeper seed routes from Bao (all 33 provider keys).
# Values flow Bao -> stdout ONLY (redirect to /tmp/seeds-live.json, deploy-only).
# NOTHING secret is stored: this file carries key names + route shapes only.
# Usage: bash scripts/render-seeds.sh > /tmp/seeds-live.json
# Deploy: nomad job run -var=seeds_json="$(cat /tmp/seeds-live.json)" keeper.nomad.hcl
set -u
PREFIX="secret/projects/pi-infinity-llm"
FALLBACK_OWNER="ksonny4@gmail.com"

get() { bao kv get -format=json "$PREFIX/$1" 2>/dev/null; }

route() { # route <KEY> <provider> <model> <base> <wire> <conn> <name> <live:1|0>
  local key="$1" doc email status cred="live:0"
  doc="$(get "$key")" || { echo "no Bao entry: $key" >&2; return 1; }
  email="$(echo "$doc" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['data'].get('email','') or '')")"
  status="$(echo "$doc" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['data'].get('status','') or '')")"
  [ -n "$email" ] || email="$FALLBACK_OWNER"
  if [ "$8" = 1 ]; then
    cred="$(echo "$doc" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']['data']; print(d.get('key') or d.get('access') or '')")"
    [ -n "$cred" ] || { echo "live key $key has no key/access value" >&2; return 1; }
  fi
  python3 - "$key" "$2" "$3" "$4" "$5" "$6" "$7" "$email" "$status" "$cred" <<'EOF'
import json, sys
key, provider, model, base, wire, conn, name, owner, status, cred = sys.argv[1:]
r = {"provider": provider, "model": model, "base_url": base,
     "wire": wire, "env_var": key, "owner": owner, "name": name,
     "connection_id": conn, "active": True,
     "bao_status": status or "unknown"}
if provider == "opencode-zen" and cred != "live:0":
    r["l2_ref"] = "opencode/big-pickle"
if cred != "live:0":
    r["api_key"] = cred
print(json.dumps(r))
EOF
}

OR_BASE="https://openrouter.ai/api/v1"
# M3 adoption (2026-09-19): Zen L1 exits via Cloudflare Worker, not OVH.
# Keyed curl through the worker returns 200 (ovh direct returns 403).
# Trade-off: Cloudflare sees the per-request Authorization header in
# transit (nothing stored at CF). Revisit if a second Mullvad key lands.
ZEN_BASE="https://keeper-zen-egress.kubelkatropkova.workers.dev/zen/v1"
ANTHropic_BASE="https://api.anthropic.com"

{
echo '{"routes": ['
first=1
emit() { if [ $first = 1 ]; then first=0; else echo ","; fi; route "$@"; }
# --- live-wire routes (credential flows into seeds) ---
emit OPENROUTER_API_KEY_2 openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini" "GPT-4o mini via OpenRouter (key 2)" 1
emit OPENROUTER_API_KEY openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini-key1" "GPT-4o mini via OpenRouter (key 1)" 1
emit OPENROUTER_API_KEY_3 openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini-key3" "GPT-4o mini via OpenRouter (key 3)" 1
emit OPENROUTER_API_KEY_4 openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini-key4" "GPT-4o mini via OpenRouter (key 4)" 1
emit OPENCODE_ZEN_API_KEY_PETR opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/big-pickle" "Big Pickle (Petr key)" 1
emit OPENCODE_ZEN_API_KEY opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/big-pickle-spare" "Big Pickle (spare key)" 1
emit GEMINI_API_KEY gemini "gemini-3.6-flash" "https://generativelanguage.googleapis.com" gemini "gemini/gemini-3.6-flash" "Gemini 3.6 Flash" 1
emit MOONSHOT_API_KEY moonshot "kimi-k2.7-code" "https://api.moonshot.ai/v1" openai "moonshot/kimi-k2.7-code" "Kimi K2.7 Code" 1
emit MUSE_CODE_OAUTH claude "claude-sonnet-4-6" "$ANTHropic_BASE" anthropic "claude/claude-sonnet-4-6" "Claude Sonnet 4.6 (oauth 1)" 1
emit MUSE_CODE_OAUTH_2 claude "claude-sonnet-4-6" "$ANTHropic_BASE" anthropic "claude/claude-sonnet-4-6-oauth2" "Claude Sonnet 4.6 (oauth 2)" 1
emit MUSE_CODE_OAUTH_3 claude "claude-sonnet-4-6" "$ANTHropic_BASE" anthropic "claude/claude-sonnet-4-6-oauth3" "Claude Sonnet 4.6 (oauth 3)" 1
# --- placeholders (no credential in seeds; unknown until a wire exists) ---
emit KILOCODE_TOKEN kilocode "kilocode-key (endpoint TBD)" "" none "kilocode/placeholder" "Kilocode token (no keeper wire yet)" 0
emit CLOUDFLARE_AI_KEY cloudflare-ai "workers-ai key 1 (no wire yet)" "" none "cloudflare/key-1" "Cloudflare AI key 1 (needs account id + wire)" 0
emit CLOUDFLARE_AI_KEY_2 cloudflare-ai "workers-ai key 2 (no wire yet)" "" none "cloudflare/key-2" "Cloudflare AI key 2 (needs account id + wire)" 0
emit CLOUDFLARE_AI_KEY_3 cloudflare-ai "workers-ai key 3 (no wire yet)" "" none "cloudflare/key-3" "Cloudflare AI key 3 (needs account id + wire)" 0
emit DEVIN_CLI_TOKEN devin-cli "devin sessions (no wire yet)" "" none "devin/placeholder" "Devin CLI token (no keeper wire yet)" 0
emit CODEX_OAUTH codex "codex (no verified wire)" "" none "codex/placeholder" "Codex OAuth (no verified keeper wire)" 0
emit ANTIGRAVITY_OAUTH antigravity "antigravity 1 (CLI-only)" "" none "antigravity/key-1" "Antigravity OAuth 1 (CLI-only, no API)" 0
emit ANTIGRAVITY_OAUTH_2 antigravity "antigravity 2 (CLI-only)" "" none "antigravity/key-2" "Antigravity OAuth 2 (CLI-only, no API)" 0
emit ANTIGRAVITY_OAUTH_INACTIVE_FRIEDMANBOB2 antigravity "inactive foreign key (placeholder)" "" none "antigravity/inactive-friedmanbob2" "Inactive Antigravity key (foreign account)" 0
emit ANTIGRAVITY_OAUTH_INACTIVE_JANNOVAK12390 antigravity "inactive foreign key (placeholder)" "" none "antigravity/inactive-jannovak12390" "Inactive Antigravity key (foreign account)" 0
emit OPENCODE_ZEN_RETIRED_1 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-1" "Big Pickle (retired key 1, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_2 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-2" "Big Pickle (retired key 2, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_3 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-3" "Big Pickle (retired key 3, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_4 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-4" "Big Pickle (retired key 4, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_5 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-5" "Big Pickle (retired key 5, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_6 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-6" "Big Pickle (retired key 6, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_7 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-7" "Big Pickle (retired key 7, owner-promoted)" 1
emit OPENCODE_ZEN_RETIRED_8 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/retired-8" "Big Pickle (retired key 8, owner-promoted)" 1
emit GITHUB_BANNED_KSONNY github "banned key (placeholder)" "" none "github/banned-ksonny" "Banned GitHub key (placeholder)" 0
emit GITHUB_BANNED_NOEMAIL github "banned key (placeholder)" "" none "github/banned-noemail" "Banned GitHub key (placeholder)" 0
emit CURSOR_UNAVAILABLE cursor "cursor (unavailable)" "" none "cursor/placeholder" "Cursor (marked unavailable in Bao)" 0
emit OPENCODE_GO_UNAVAILABLE opencode-go "opencode-go (unavailable)" "" none "opencode-go/placeholder" "Opencode Go (marked unavailable in Bao)" 0
echo ""
echo ']}'
} 
