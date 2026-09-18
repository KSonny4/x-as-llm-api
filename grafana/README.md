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

## Import the rule (Grafana Cloud meowlabs, UI path)

1. Wake the stack if hibernated (open it in a browser first).
2. Alerting → Alert rules → New → **Import**: paste
   `grafana/keeper-divergent-alert.json`.
3. Replace `DATASOURCE_UID` with your Prometheus uid (the preview shows
   `Data source not found` until you do).
4. Attach your contact point in `notifications` (rule ships with none —
   deliberate: paging target is an owner call).
5. `for: 0s` fires immediately on any divergent==1 (calibrated choice:
   splits are rare and always actionable; persistence can be added later
   per L4 without changing the signal).

## API path (currently blocked)

`secret/projects/ovhcloud/GRAFANA_CLOUD_RW` returns `Invalid API key`
(checked 2026-09-18) — when a fresh Cloud token lands, apply via
`POST /api/v1/provisioning/alert-rules` with this file (after filling
`DATASOURCE_UID` + `notifications`) instead of the UI steps above.
