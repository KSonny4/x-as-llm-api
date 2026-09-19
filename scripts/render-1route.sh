#!/usr/bin/env bash
# render-1route.sh KEY MODEL CONN — one zen seed route, Bao -> stdout.
# Same fields/credentials flow as render-seeds.sh; values never in git.
# Usage: SEEDS1="$(bash scripts/render-1route.sh OPENCODE_ZEN_RETIRED_5 \
#            muse-spark-1.3-contributor-free zen/spark13-retired-5)"
set -u
PREFIX="secret/projects/pi-infinity-llm"
ZEN_BASE="https://opencode.ai/zen/v1"
key="$1" model="$2" conn="$3"
doc="$(bao kv get -format=json "$PREFIX/$key")" || exit 1
python3 - "$doc" "$key" "$model" "$conn" <<'EOF'
import json, sys
doc = json.loads(sys.argv[1])["data"]["data"]
key, model, conn = sys.argv[2:]
cred = doc.get("key") or doc.get("access") or ""
if not cred:
    sys.exit("live key %s has no key/access value" % key)
r = {"provider": "opencode-zen", "model": model, "base_url": "https://opencode.ai/zen/v1",
     "wire": "openai", "env_var": key,
     "owner": doc.get("email", "") or "ksonny4@gmail.com",
     "name": "%s (%s)" % (model, key), "connection_id": conn,
     "active": True, "bao_status": doc.get("status", "") or "unknown",
     "l2_ref": "opencode/" + model, "api_key": cred}
print(json.dumps({"routes": [r]}))
EOF
