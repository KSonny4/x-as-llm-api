#!/usr/bin/env bash
# smoke.sh — phase gate. Takes base URL; local-only green gates nothing.
# Usage: bash scripts/smoke.sh [BASE_URL]  (default http://localhost:8080)
set -u
BASE="${1:-http://localhost:8080}"
BODY=$(curl -s -m 10 -w "\n%{http_code}" "$BASE/healthz")
CODE=$(echo "$BODY" | tail -1)
TEXT=$(echo "$BODY" | head -1)
if [ "$CODE" = 200 ] && [ "$TEXT" = ok ]; then
  echo "ok: $BASE/healthz -> 200 ok"
else
  echo "FAIL: $BASE/healthz -> $CODE [$TEXT]"; exit 1
fi
U_CODE=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "$BASE/packs")
if [ "$U_CODE" = 401 ]; then
  echo "ok: $BASE/packs unauth -> 401"
else
  echo "FAIL: $BASE/packs unauth -> $U_CODE (want 401)"; exit 1
fi
