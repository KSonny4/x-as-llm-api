#!/bin/sh
# probe-entry.sh: stage opencode auth (if mounted) then run the prober.
# OPENCODE_AUTH_FILE points at the Nomad-templated auth.json; values never
# touch the image — the file arrives at deploy time via -var.
set -u
if [ -n "${OPENCODE_AUTH_FILE:-}" ] && [ -f "$OPENCODE_AUTH_FILE" ]; then
  mkdir -p "$HOME/.local/share/opencode"
  cp "$OPENCODE_AUTH_FILE" "$HOME/.local/share/opencode/auth.json"
  chmod 600 "$HOME/.local/share/opencode/auth.json"
fi
exec "$@"
