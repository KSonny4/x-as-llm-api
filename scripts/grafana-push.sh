#!/bin/bash
# Push the Keeper usage dashboard + alert rules to Grafana Cloud (meowlabs).
#
# Auth: gcx context my-stack (non-expiring service-account token; Bao
# secret/projects/nomad/GRAFANA_CLI_TOKEN field token on other machines:
#   GRAFANA_SERVER=https://meowlabs.grafana.net GRAFANA_TOKEN=$(bao kv get ...)).
# Generated JSON comes from scripts/grafana_usage_dashboard.py (validated there).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/grafana_usage_dashboard.py
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

jq -n --slurpfile d grafana/keeper-usage-dashboard.json \
  '{dashboard: $d[0], folderUid: "keeper", overwrite: true,
    message: "keeper usage & cost (scripts/grafana-push.sh)"}' > "$tmp/dash.json"
gcx api /api/dashboards/db -d @"$tmp/dash.json" | jq -c '{status, uid, url, version}'

n=$(jq length grafana/keeper-usage-alerts.json)
for i in $(seq 0 $((n - 1))); do
  jq ".[$i]" grafana/keeper-usage-alerts.json > "$tmp/rule.json"
  uid=$(jq -r .uid "$tmp/rule.json")
  if gcx api "/api/v1/provisioning/alert-rules/$uid" >/dev/null 2>&1; then
    gcx api "/api/v1/provisioning/alert-rules/$uid" -X PUT -d @"$tmp/rule.json" \
      -H 'X-Disable-Provenance: true' | jq -c '{uid, title, updated}'
  else
    gcx api /api/v1/provisioning/alert-rules -d @"$tmp/rule.json" \
      -H 'X-Disable-Provenance: true' | jq -c '{uid, title, updated}'
  fi
done
