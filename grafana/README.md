# Keeper Grafana alerting

## Signal

`keeper_route_divergent{provider,model,connection}` (0/1) from keeper
`GET /metrics` — 1 means L1 curl failed while L2 opencode CLI passed on
the same route+run. Plain `down` never pages here by design.

## Scrape (Prometheus)

```yaml
- job_name: keeper
  metrics_path: /metrics
  static_configs:
    - targets: ['keeper.pkubelka.cz:443']
      scheme: https
  authorization:
    credentials: <KEEPER_TOKEN>   # same bearer as /packs; never in git
```

## Create the rule (Grafana Cloud meowlabs, UI path)

`keeper-divergent-alert.json` is file-provisioning format (for API apply
or self-hosted provisioning) — the Cloud UI has no JSON-paste import for
rules, so recreate it via Alerting → Alert rules → New alert rule:

- Folder: `keeper` (create it) · Group: `keeper-divergence` · Interval: `1m`
- Query (Prometheus datasource scraping keeper `/metrics`, see below):
  `max by (provider, model, connection) (keeper_route_divergent)`
- Expression (threshold): `fire` = last of query `> 0`; `for: 0s`
  (fires immediately on any divergent==1 — splits are rare and always
  actionable; persistence can calibrate later per L4)
- Labels: `severity=page`, `service=keeper`
- Annotations: summary `L1/L2 split on {{ $labels.provider }}/{{ $labels.model }}`;
  description with matrix link + runbook pointer (see the JSON file)
- Notifications: attach YOUR contact point (deliberately unfilled here —
  paging target is an owner call)
- `grafana/condition-check-2026-09-18.json` proves the condition holds on
  live data right now (`max` = 1.0 → FIRING); the presentation half
  (rule rendered in UI) is the owner step below.

## API path (currently blocked)

`secret/projects/ovhcloud/GRAFANA_CLOUD_RW` returns `Invalid API key`
(checked 2026-09-18) — when a fresh Cloud token lands, apply via
`POST /api/v1/provisioning/alert-rules` with this file (after filling
`DATASOURCE_UID` + `notifications`) instead of the UI steps above.
