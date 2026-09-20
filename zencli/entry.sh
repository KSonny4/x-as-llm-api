#!/bin/sh
# zencli-entry.sh: stage opencode auth (if mounted), start the server,
# POST one echo prompt, print the answer. Alloc log = receipt.
set -u
if [ -n "${OPENCODE_AUTH_FILE:-}" ] && [ -f "$OPENCODE_AUTH_FILE" ]; then
  mkdir -p "$HOME/.local/share/opencode"
  cp "$OPENCODE_AUTH_FILE" "$HOME/.local/share/opencode/auth.json"
  chmod 600 "$HOME/.local/share/opencode/auth.json"
fi
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
