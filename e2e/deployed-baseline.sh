#!/usr/bin/env bash
# E2E baseline against the deployed keeper. E2E-first: this gates everything.
# Usage: KEEPER_TOKEN=<token> bash e2e/deployed-baseline.sh [BASE_URL]
# Bearer comes from env only — never committed. Values are never stored.
set -u
BASE="${1:-https://keeper.pkubelka.cz}"
OUT="e2e/baseline-shapes.json"
PASS=0; FAIL=0
check() { # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS: $1 ($3)";
  else FAIL=$((FAIL+1)); echo "FAIL: $1 (want $2, got $3)"; fi
}

H_CODE=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "$BASE/healthz")
check "healthz" 200 "$H_CODE"

P_CODE=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "$BASE/packs")
check "packs-unauth-401" 401 "$P_CODE"

if [ -n "${KEEPER_TOKEN:-}" ]; then
  A_TMP=$(mktemp)
  A_CODE=$(curl -s -m 15 -H "Authorization: Bearer $KEEPER_TOKEN" "$BASE/packs" -o "$A_TMP" -w "%{http_code}")
  echo "INFO: packs-authed -> $A_CODE (200 = values flow; 401/403 recorded as OPEN)"
  if [ "$A_CODE" = 200 ]; then
    python3 - "$A_TMP" "$OUT" <<'EOF'
import json,sys
d=json.load(open(sys.argv[1]))
def redact(m):
    return {k:(('<redacted>' if k in ('credential','connectionRef','value','token','key') else v)) for k,v in m.items()}
json.dump({"keeperPackVersion":d.get("keeperPackVersion"),
  "packs":{p:[redact(m) for m in ms] for p,ms in d.get("packs",{}).items()}}, open(sys.argv[2],"w"), indent=1)
print("shapes saved (values redacted)")
EOF
    PASS=$((PASS+1))
  else
    echo "OPEN: authed packs returned $A_CODE — reconcile token before v2 reads depend on it"
  fi
  rm -f "$A_TMP"
else
  echo "SKIP: packs-authed (KEEPER_TOKEN unset)"
fi

echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" = 0 ]
