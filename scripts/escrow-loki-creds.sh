#!/bin/bash
# Escrow Grafana Loki push credentials to Bao (operator terminal only).
# The values never appear in stdout/logs/history: silent reads, no `set -x`.
# Usage: ./scripts/escrow-loki-creds.sh
set -u
printf 'Loki numeric instance/user ID: '
IFS= read -r LOKI_USER
printf 'Loki token (logs:write scope): '
IFS= read -rs LOKI_TOKEN
printf '\n'
[ -n "$LOKI_USER" ] && [ -n "$LOKI_TOKEN" ] || { echo 'empty value; aborted' >&2; exit 1; }
bao kv put secret/projects/nomad/GRAFANA_CLOUD_LOKI user="$LOKI_USER" token="$LOKI_TOKEN" >/dev/null || exit 1
unset LOKI_USER LOKI_TOKEN
echo 'escrowed. Tell the agent to wire Alloy.'
