# Keeper Grafana health report — 2026-09-18/19

Every item below was read live; evidence paths are committed captures,
not prose. No Telegram test pages were ever sent — `firing` below is a
real route state, `normal`/`nodata` are captured rule evaluations.

## Alerts (folder `keeper`, all → HonzaTraderBot)

| Rule | State @ evaluated-at | Health | Evidence |
|---|---|---|---|
| keeper-route-divergent | inactive @ 2026-09-18T23:57:30Z | ok | `docs/m3-live/grafana-rule-state.json` + rule GET `grafana/keeper-divergent-alert.json` |
| keeper-route-down | **firing** @ 2026-09-18T23:57:10Z | ok | real down routes exist (both legs fail); `grafana/keeper-route-down.json` (provisioning GET) |
| keeper-probe-stale | inactive @ 2026-09-18T23:57:10Z | ok | fresh probes landed after the earlier nodata reading; max age under threshold; `grafana/keeper-probe-stale.json` |

Rule files committed verbatim from provisioning GETs:
`grafana/keeper-divergent-alert.json`, `grafana/keeper-route-down.json`,
`grafana/keeper-probe-stale.json` — each `datasourceUid:
grafanacloud-prom`, `notification_settings.receiver: HonzaTraderBot`.

## Shipper + token scopes

| Check | Result |
|---|---|
| Alloy series in Cloud (`count(keeper_route_divergent)`) | PASS — 11, age seconds at capture |
| `keeper_route_down` in Cloud | PASS — 11 |
| `keeper_probe_checked_at_seconds` in Cloud | PASS — 11 |
| Service-account token (API: provisioning, dashboards, proxy) | PASS — 200s across all calls above |
| Metrics-write basic-auth for Alloy re-register | FAIL (open) — stack tokens carry no Prometheus basic-auth; running Alloy ships on its baked pair. Owner console step, recorded non-blocking. |

## Dashboard

`grafana/keeper-routes-dashboard.json` (uid `keeper-routes`, folder
`keeper`): divergent table, down table, freshness stat (red > 900s).
Applied 200, API GET returns 3/3 panels (`grafana/dashboard-get.json`).
Down panel was honestly-empty until M2 landed the series; now populated.

## Suites

keeper 122 + probe 16 green (M2 added the down-gauge test);
`keeper/tripwire.sh` CLEAN; no secret values in git (names/paths only).
