#!/bin/bash
# Escrow Grafana Tempo push credentials to Bao (operator terminal only).
# The value never appears in stdout/logs/history: silent read, no `set -x`.
# Instance/user ID for the meowlabs stack is 1470731 (verified 2026-09-22).
# Usage: ./scripts/escrow-tempo-creds.sh
set -u
printf 'Tempo token (traces:write scope, silent input): '
IFS= read -rs TEMPO_TOKEN
printf '\n'
[ -n "$TEMPO_TOKEN" ] || { echo 'empty value; aborted' >&2; exit 1; }
bao kv put secret/projects/nomad/GRAFANA_CLOUD_TRACES token="$TEMPO_TOKEN" >/dev/null || exit 1
unset TEMPO_TOKEN
echo 'escrowed. Tell the agent to verify the push.'
