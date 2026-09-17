#!/usr/bin/env bash
# smoke.sh — phase gate. Takes base URL; local-only green gates nothing.
# Usage: KEEPER_TOKEN=<token> bash scripts/smoke.sh [BASE_URL]
#   (default http://localhost:8080). Authed gates run only when
#   KEEPER_TOKEN is set; chat/completions needs a stubbed upstream and is
#   covered by keeper/test_server.py instead.
set -u
BASE="${1:-http://localhost:8080}"
FAIL=0
ok() { echo "ok: $1"; }
fail() { echo "FAIL: $1"; FAIL=1; }
expect() { # expect <name> <want> <got>
  if [ "$2" = "$3" ]; then ok "$1 -> $3"; else fail "$1 (want $2, got $3)"; fi
}

BODY=$(curl -s -m 10 -w "\n%{http_code}" "$BASE/healthz")
expect "$BASE/healthz 200 ok" "200
ok" "$(echo "$BODY" | tail -1)
$(echo "$BODY" | head -1)"

expect "$BASE/packs unauth 401" 401 \
  "$(curl -s -m 10 -o /dev/null -w "%{http_code}" "$BASE/packs")"

if [ -z "${KEEPER_TOKEN:-}" ]; then
  echo "SKIP: authed gates (KEEPER_TOKEN unset)"
  [ "$FAIL" = 0 ]
  exit "$FAIL"
fi
A="Authorization: Bearer $KEEPER_TOKEN"

PACKS_TMP=$(mktemp)
P_CODE=$(curl -s -m 10 -H "$A" "$BASE/packs" -o "$PACKS_TMP" -w "%{http_code}")
expect "$BASE/packs authed 200" 200 "$P_CODE"
TAG=$(curl -s -m 10 -D - -H "$A" -o /dev/null "$BASE/packs" \
  | grep -i '^ETag:' | tr -d '\r' | awk '{print $2}')
if [ -n "$TAG" ]; then
  expect "$BASE/packs 304" 304 \
    "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" \
      -H "If-None-Match: $TAG" "$BASE/packs")"
else
  fail "$BASE/packs missing ETag"
fi
rm -f "$PACKS_TMP"

expect "$BASE/v1/providers 200" 200 \
  "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" "$BASE/v1/providers")"
expect "$BASE/v1/models 200" 200 \
  "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" "$BASE/v1/models")"
expect "$BASE/v1/guide/curl 200" 200 \
  "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" "$BASE/v1/guide/curl")"
expect "$BASE/api/v1/matrix 200" 200 \
  "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" "$BASE/api/v1/matrix")"
expect "$BASE/api/v1/health 200" 200 \
  "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" "$BASE/api/v1/health")"

IDX=$(curl -s -m 10 -H "$A" "$BASE/")
case "$IDX" in
  *"<table>"*diagnostics.unassigned*) ok "$BASE/ table + unassigned" ;;
  *) fail "$BASE/ missing table/unassigned" ;;
esac

for page in guides signin report; do
  expect "$BASE/$page 200" 200 \
    "$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" "$BASE/$page")"
done

FB_BAD=$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" \
  -H "Content-Type: application/json" -d '{"provider":"smoke"}' "$BASE/feedback")
expect "$BASE/feedback bad 422" 422 "$FB_BAD"
FB_OK=$(curl -s -m 10 -o /dev/null -w "%{http_code}" -H "$A" \
  -H "Content-Type: application/json" \
  -d '{"provider":"smoke","model":"smoke","errorClass":"unknown","httpStatus":500,"keeperPackVersion":"v2"}' \
  "$BASE/feedback")
expect "$BASE/feedback good 202" 202 "$FB_OK"

[ "$FAIL" = 0 ]
