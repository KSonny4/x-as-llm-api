# M3 live receipt — :main-91c7cb8, 5-route reseed (2026-09-18)

Proves the all-models matrix is live on `main` (fix: `GET /packs` serves
the live inventory, not just seed routes). Each file is a captured
artifact, re-verifiable as noted.

- `arch.txt` — `docker inspect`: `arch=amd64` + image digest.
- `alloc.txt` — Nomad `keeper` running alloc id + job version.
- `healthz.txt` — public `GET /healthz` → 200.
- `packs.json` — public `GET /packs` (credential values redacted to
  `{type, present}`): 500 packs, every `path: infinity/<provider>/<model>`
  — 5 seeded routes with credentials/signin as before, plus 495
  inventory-only signin packs (openrouter 445, gemini 49, moonshot 1),
  incl. `infinity/claude/claude-sonnet-4-6`. The full enumerated list is
  in packs (uncapped); the matrix caps display columns at 20/provider
  with overflow in `diagnostics.inventory_more`.
- `matrix.txt` — public matrix: 1 email row, 5 routed columns with real
  states + `l1`/`l2` + `checked_at` (fresh `keeper-probe` dispatch at
  capture time), 46 total columns,
  `inventory_more: {openrouter: 425, gemini: 29}`.
- `metrics.txt` — 5 `keeper_route_divergent` series (all 0 here: no
  L1-fail+L2-pass split at capture time).
- `reseed.json` — the 5-route seed source (api_key values redacted to
  presence+length): rotated OpenRouter key (`_2`), unchanged zen,
  new gemini-3.6-flash (Google retired 2.5-flash for new users),
  kimi-k2.7-code, claude-sonnet-4-6 (documented Anthropic ID).
  The same content (with values, deploy-only) is passed via Nomad `-var`.
- `tripwire.log` — `keeper/tripwire.sh` output: CLEAN (script matches
  real key formats; short fixture stubs structurally excluded).

Notes: Gemini/Moonshot states vary run to run (depleted prepay / 429) —
both are honest provider-side states, not code faults. Probe detail
(`l1`/`l2`/`checked_at`) is in-memory server state: a redeploy resets
cells to unknown until the next `keeper-probe` dispatch; that is why
`matrix.txt` is captured right after a dispatch. No UI screenshot
is attached: this environment has no image-input path, so visual proof
is unavailable rather than invented; the page HTML is asserted in tests
(legend, colors, Muse column, poller).

## Addendum 2026-09-18 — 33-key reseed (job v20, images :main-76660e7)

All 33 `secret/projects/pi-multi-providers/` keys seeded via
`scripts/render-seeds.sh` (values Bao→`/tmp` only, never git): 11 live
routes with credentials (openrouter ×4, zen ×2, gemini, moonshot, claude
OAuth ×3 — same-model spares share columns, each keeps its own verdict
via per-`connection_id` probe ingest) + 22 keyless placeholders
(`wire: none`, never probed, honestly `unknown`): kilocode, cloudflare
×3, devin, codex, antigravity ×2, 2 inactive foreign keys, 8 retired
zen, 2 banned github, cursor + opencode-go unavailable. Owners come from
Bao `email` metadata (8 distinct rows; empty → operator fallback,
documented per route). `reseed-33.json` holds the redacted shape.
`packs.json` now 528 packs (11 credential + 517 signin); `matrix.txt` 8
emails × 66 columns, 11 live cells with `checked_at`, 22 placeholders
`unknown` without `checked_at` (never probed — by design, not by gap).
Zen `l2_ref: opencode/big-pickle` preserved on both live zen routes.

## Addendum 2026-09-19 — Alloy shipper live + KEEPER_TOKEN rotation

- `keeper-alloy.nomad.hcl` committed with one fix: Nomad template
  destinations must be task-relative — the absolute
  `/etc/alloy/config.alloy` never rendered (alloc ran Alloy's stock
  example config). Now `local/config.alloy` via `${NOMAD_TASK_DIR}`.
- Shipper deployed (`keeper-alloy` service, Alloy v1.19.2), creds from
  Bao `secret/projects/nomad/GRAFANA_CLOUD_RW` (`user`+`token`, passed
  via `-var`, never git). Cloud query
  `count(keeper_route_divergent)` → **11 series** (all live routes),
  verified via the Hosted Prometheus API (the `grafanacloud-prom`
  datasource proxy needs a working Grafana API key — Bao's
  `GRAFANA_CLOUD_API_KEY` returns 401 invalid).
- KEEPER_TOKEN rotated (Bao v3) after the old value appeared in an
  operator debug transcript: parallel-accept window (old 200 + new
  200) → cutover (old 401, new 200) → Alloy + keeper-probe jobs
  re-registered on the new token. Old token rejected everywhere.
- STILL OWNER-ONLY: Grafana alert-rule apply (needs a working Cloud
  API token with alerting write) + contact-point choice
  (`notifications: []` stays empty until then).

## Addendum 2026-09-18T22:43Z — alert rule APPLIED, state captured live

- Token: Bao `secret/projects/nomad/GRAFANA_CLOUD_RW` (admin,
  Bearer-authenticated against `https://meowlabs.grafana.net/api`).
  Bao `control-panel/GRAFANA_CLOUD_API_KEY` is 401-invalid (dead).
- Rule: folder `keeper`, group `keeper-divergence`, uid
  `keeper-route-divergent`, `datasourceUid: grafanacloud-prom`,
  `notification_settings.receiver: HonzaTraderBot` (telegram, uid
efcikfz53nr40e, owner-confirmed). `grafana/keeper-divergent-alert.json`
  updated to the applied A→B→C shape; lessons recorded in its `_comment`.
- Live state @ 2026-09-18T22:43:30Z: **inactive / health ok** — correct,
  all 11 series are 0 (no L1-fail+L2-pass split exists); nothing faked.
  Test-firing to the owner's Telegram was NOT done (noise, unasked).
- Deleted same-day: stale twin `cfyn4k7ofc16of` (earlier 2-stage attempt,
  no receiver, permanent eval error) + `keeper-bisect` scratch group.
- Caveat (2026-09-19, worker-verified): the RW token does NOT authenticate
  Prometheus basic-auth, and post-revocation the baked basic pair is dead
  too — Cloud shows 0 series: green alloc shipping nothing (the exact
  failure mode warned about). Re-registering Alloy needs the fresh
  metrics-write token escrowed; `keeper-alloy.nomad.hcl` is prepped
  (password via `env("GRAFANA_TOKEN")`, validated, commit 2922546).
  Owner: revoke exposed token, mint fresh under the alloy metrics:write
  policy, escrow via owner terminal, record expiry in #85 — then tell
  the agent to re-register + JIT-verify.

## Addendum — audit capture files + token revocation (job v26, :main-382c2cd)

- `alloc.txt` is now a full `nomad job status keeper` capture (v26
  running, image `main-382c2cd` + digest appended); `alloy-job.txt` the
  same for `keeper-alloy` (v2 running). `arch.txt` re-pinned to the
  current digest. packs/matrix/metrics/healthz re-captured (528 packs,
  11 checked_at + AA scores in matrix, 11 metric series).
- `grafana/keeper-divergent-alert.json` now mirrors the applied rule
  field-for-field (condition C, A→B→C, `notification_settings.receiver:
  HonzaTraderBot`); legacy `notifications` key removed.
- 2026-09-19 ~01:00Z: Bao `nomad/GRAFANA_CLOUD_RW` token revoked
  (exposed-token hygiene) — Grafana API + Hosted-Prometheus captures
  (`prom-query.json`, `grafana-rule-get.json`, `grafana-rule-state.json`)
  are staged pending owner escrow of the fresh token to the same Bao
  path/field via owner terminal. Rule + shipper verified working before
  revocation (11 series, inactive/health-ok @22:43:30Z); running Alloy
  unaffected (baked basic pair).
