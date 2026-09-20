#!/usr/bin/env bash
# render-seeds.sh — render keeper seed routes from Bao (33 provider keys +
# zen free-model sweep: 7 free models x 10 zen keys = 70 e2e routes).
# Values flow Bao -> stdout ONLY (redirect to /tmp/seeds-live.json, deploy-only).
# NOTHING secret is stored: this file carries key names + route shapes only.
# Usage: bash scripts/render-seeds.sh > /tmp/seeds-live.json
# Deploy: nomad job run -var=seeds_json="$(cat /tmp/seeds-live.json)" keeper.nomad.hcl
set -euo pipefail
PREFIX="secret/projects/pi-infinity-llm"
get() { bao kv get -format=json "$PREFIX/$1" 2>/dev/null; }

route() { # route <KEY> <provider> <model> <base> <wire> <conn> <name> <legacy-live>
  local key="$1" doc
  doc="$(get "$key")" || { echo "no Bao entry: $key" >&2; return 1; }
  # Secret document goes through stdin, never process arguments. Missing values
  # remain visible/signin-required rather than creating a fabricated credential.
  printf '%s' "$doc" | python3 -c '
import json, sys
key, provider, model, base, wire, conn, name = sys.argv[1:]
doc = json.load(sys.stdin)["data"]
d = doc["data"]
version = doc.get("metadata", {}).get("version")
if not isinstance(version, int) or version < 1:
    raise SystemExit("seed metadata requires a Bao credential generation")
status = str(d.get("status") or "unknown")
r = {"provider": provider, "model": model, "base_url": base,
     "wire": wire, "env_var": key, "owner": d.get("email") or "", "name": name,
     "credential_ref": key + "@bao:" + str(version),
     "connection_id": conn, "bao_status": status,
     "active": status.lower() not in ("disabled", "retired", "inactive", "revoked", "banned")}
cred = d.get("key") or d.get("access")
if isinstance(cred, str) and cred.strip():
    r["api_key"] = cred
for field in ("account_id", "free_tier", "no_paid_fallback", "tier_provenance"):
    if field in d:
        r[field] = d[field]
eligibility = d.get("model_eligibility", {}).get(model)
if isinstance(eligibility, dict):
    r["free_eligibility"] = eligibility
print(json.dumps(r))
' "$key" "$2" "$3" "$4" "$5" "$6" "$7"
}

OR_BASE="https://openrouter.ai/api/v1"
# Root-cause fix (2026-09-19): direct Zen with fleet UA (the 403 was
# the Python-urllib default UA, never the OVH IP). Worker parked spare.
ZEN_BASE="https://opencode.ai/zen/v1"
ANTHropic_BASE="https://api.anthropic.com/v1"

{
echo '{"routes": ['
first=1
emit() { if [ $first = 1 ]; then first=0; else echo ","; fi; route "$@"; }
# --- live-wire routes (credential flows into seeds) ---
emit OPENROUTER_API_KEY_2 openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini" "GPT-4o mini via OpenRouter (key 2)" 1
emit OPENROUTER_API_KEY openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini-key1" "GPT-4o mini via OpenRouter (key 1)" 1
emit OPENROUTER_API_KEY_3 openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini-key3" "GPT-4o mini via OpenRouter (key 3)" 1
emit OPENROUTER_API_KEY_4 openrouter "openai/gpt-4o-mini" "$OR_BASE" openai "openrouter/gpt-4o-mini-key4" "GPT-4o mini via OpenRouter (key 4)" 1
# Historical order is retained for legacy consumers; availability never treats
# route order or CLI results as evidence. Bao status, not key names, controls activity.
emit OPENCODE_ZEN_RETIRED_1 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-1" "Big Pickle (pool key 1)" 1
emit OPENCODE_ZEN_API_KEY opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-spare" "Big Pickle (pool spare key)" 1
emit OPENCODE_ZEN_API_KEY_PETR opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-petr" "Big Pickle (pool Petr key)" 1
emit GEMINI_API_KEY gemini "gemini-3.6-flash" "https://generativelanguage.googleapis.com/v1beta" gemini "gemini/gemini-3.6-flash" "Gemini 3.6 Flash" 1
emit MOONSHOT_API_KEY moonshot "kimi-k2.7-code" "https://api.moonshot.ai/v1" openai "moonshot/kimi-k2.7-code" "Kimi K2.7 Code" 1
emit MUSE_CODE_OAUTH claude "claude-sonnet-4-6" "$ANTHropic_BASE" anthropic "claude/claude-sonnet-4-6" "Claude Sonnet 4.6 (oauth 1)" 1
emit MUSE_CODE_OAUTH_2 claude "claude-sonnet-4-6" "$ANTHropic_BASE" anthropic "claude/claude-sonnet-4-6-oauth2" "Claude Sonnet 4.6 (oauth 2)" 1
emit MUSE_CODE_OAUTH_3 claude "claude-sonnet-4-6" "$ANTHropic_BASE" anthropic "claude/claude-sonnet-4-6-oauth3" "Claude Sonnet 4.6 (oauth 3)" 1
# --- unsupported adapters remain accounted for; real metadata is retained ---
emit KILOCODE_TOKEN kilocode "" "https://api.kilo.ai/api/gateway" openai "kilocode/catalog" "Kilo Gateway" 1
emit CLOUDFLARE_AI_KEY cloudflare-ai "workers-ai (adapter unsupported)" "" none "cloudflare/key-1" "Cloudflare AI key 1 (adapter unsupported)" 0
emit CLOUDFLARE_AI_KEY_2 cloudflare-ai "workers-ai (adapter unsupported)" "" none "cloudflare/key-2" "Cloudflare AI key 2 (adapter unsupported)" 0
emit CLOUDFLARE_AI_KEY_3 cloudflare-ai "workers-ai (adapter unsupported)" "" none "cloudflare/key-3" "Cloudflare AI key 3 (adapter unsupported)" 0
emit DEVIN_CLI_TOKEN devin-cli "devin sessions (no wire yet)" "" none "devin/placeholder" "Devin CLI token (no keeper wire yet)" 0
emit CODEX_OAUTH codex "codex (no verified wire)" "" none "codex/placeholder" "Codex OAuth (no verified keeper wire)" 0
emit ANTIGRAVITY_OAUTH antigravity "antigravity 1 (CLI-only)" "" none "antigravity/key-1" "Antigravity OAuth 1 (CLI-only, no API)" 0
emit ANTIGRAVITY_OAUTH_2 antigravity "antigravity 2 (CLI-only)" "" none "antigravity/key-2" "Antigravity OAuth 2 (CLI-only, no API)" 0
emit ANTIGRAVITY_OAUTH_INACTIVE_FRIEDMANBOB2 antigravity "inactive foreign key (placeholder)" "" none "antigravity/inactive-friedmanbob2" "Inactive Antigravity key (foreign account)" 0
emit ANTIGRAVITY_OAUTH_INACTIVE_JANNOVAK12390 antigravity "inactive foreign key (placeholder)" "" none "antigravity/inactive-jannovak12390" "Inactive Antigravity key (foreign account)" 0
emit OPENCODE_ZEN_RETIRED_2 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-2" "Big Pickle (pool key 2)" 1
emit OPENCODE_ZEN_RETIRED_3 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-3" "Big Pickle (pool key 3)" 1
emit OPENCODE_ZEN_RETIRED_4 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-4" "Big Pickle (pool key 4)" 1
emit OPENCODE_ZEN_RETIRED_5 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-5" "Big Pickle (pool key 5)" 1
emit OPENCODE_ZEN_RETIRED_6 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-6" "Big Pickle (pool key 6)" 1
emit OPENCODE_ZEN_RETIRED_7 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-7" "Big Pickle (pool key 7)" 1
emit OPENCODE_ZEN_RETIRED_8 opencode-zen "big-pickle" "$ZEN_BASE" openai "zen/pool-8" "Big Pickle (pool key 8)" 1
# --- historical seed inventory; fresh provider pricing controls eligibility ---
for spec in \
  "ling-3.0-flash-fin-free:ling-flash:Ling Flash (free)" \
  "mimo-v2.5-free:mimo:Mimo (free)" \
  "muse-spark-1.2-contributor-free:spark12:Muse Spark 1.2 (free)" \
  "muse-spark-1.3-contributor-free:spark13:Muse Spark 1.3 (free)" \
  "nemotron-3-ultra-free:nemotron-ultra:Nemotron Ultra (free)" \
  "nemotron-3.5-lightning-free:nemotron-lightning:Nemotron Lightning (free)" \
  "jev-1.13-free:jev113:Jev 1.13 (free)"; do
  model="${spec%%:*}"; rest="${spec#*:}"; tag="${rest%%:*}"; label="${rest#*:}"
  # Repeated routes share one Bao-versioned credential reference.
  emit OPENCODE_ZEN_RETIRED_1 opencode-zen "$model" "$ZEN_BASE" openai "zen/$tag-pool-1" "$label (pool key 1)" 1
  emit OPENCODE_ZEN_API_KEY_PETR opencode-zen "$model" "$ZEN_BASE" openai "zen/$tag-pool-petr" "$label (pool Petr key)" 1
  emit OPENCODE_ZEN_API_KEY opencode-zen "$model" "$ZEN_BASE" openai "zen/$tag-pool-spare" "$label (pool spare key)" 1
  n=2; while [ $n -le 8 ]; do
    emit "OPENCODE_ZEN_RETIRED_$n" opencode-zen "$model" "$ZEN_BASE" openai "zen/$tag-pool-$n" "$label (pool key $n)" 1
    n=$((n+1))
done
done
emit GITHUB_BANNED_KSONNY github "banned key (placeholder)" "" none "github/banned-ksonny" "Banned GitHub key (placeholder)" 0
emit GITHUB_BANNED_NOEMAIL github "banned key (placeholder)" "" none "github/banned-noemail" "Banned GitHub key (placeholder)" 0
emit CURSOR_UNAVAILABLE cursor "cursor (unavailable)" "" none "cursor/placeholder" "Cursor (marked unavailable in Bao)" 0
emit OPENCODE_GO_UNAVAILABLE opencode-go "opencode-go (unavailable)" "" none "opencode-go/placeholder" "Opencode Go (marked unavailable in Bao)" 0
echo ""
echo ']}'
} 
