#!/bin/sh
# zencli-entry.sh: stage opencode auth (if mounted), start the server,
# POST one echo prompt, print the answer. Alloc log = receipt.
set -u
# Guard the -var: reject omitted, empty, and placeholder {} auth BEFORE
# staging credentials or starting anything that touches the vendor.
# (The hcl default is "{}" so a forgotten -var fails closed, never open.)
AUTH_SRC="${OPENCODE_AUTH_FILE:-}"
if [ -z "$AUTH_SRC" ] || [ ! -f "$AUTH_SRC" ]; then
  echo "refusing: OPENCODE_AUTH_FILE unset or missing (pass -var=opencode_auth_json)" >&2
  exit 2
fi
stripped="$(tr -d '[:space:]' < "$AUTH_SRC")"
if [ -z "$stripped" ] || [ "$stripped" = "{}" ]; then
  echo "refusing: opencode auth empty or placeholder {} (pass real -var=opencode_auth_json)" >&2
  exit 2
fi
mkdir -p "$HOME/.local/share/opencode"
cp "$AUTH_SRC" "$HOME/.local/share/opencode/auth.json"
chmod 600 "$HOME/.local/share/opencode/auth.json"
PORT="${ZENCLI_PORT:-8099}"
/srv/zencli/zencli -port "$PORT" > /tmp/zencli-serve.log 2>&1 &
SRV=$!
for _ in $(seq 1 30); do
  curl -s -m 2 -o /dev/null "http://127.0.0.1:${PORT}/v1/models" && break
  sleep 1
done
curl -s -m 100 -X POST "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"big-pickle","messages":[{"role":"user","content":"Reply with exactly: NOMAD-ZENCLI-ALIVE"}],"stream":false}'
echo
kill $SRV 2>/dev/null
