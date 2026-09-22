# Engineering guidance: consuming Keeper

**Protected baseline: original zencli works on Nomad.** Its unchanged HTTP
wrapper returned **200** for `big-pickle` using the successful local-login key.
Read [the control receipt](zencli-sanity-check.md) before changing integration.
Preserve the original; use it as the sanity check, not a replacement profile.

**LIVE (Nomad job `keeper` v15):** the contract below is
verified on `https://keeper.pkubelka.cz` — service `keeper-coder` chat HTTP 200
on production; canary exact-CLI observation WORKING + admin exact chat HTTP 200.
The original control still passes alongside. Consumers may point OpenAI clients
at the service API per "Other-service configuration".

## Other-service configuration

Use the existing OpenAI-compatible client with base URL
`https://keeper.pkubelka.cz/v1`, model `keeper-coder`, and the non-expiring
inference-only token from your service secret store. Operator source:
Bao `secret/projects/pi-infinity-llm/KEEPER_SERVICE_TOKEN`, field `token`.
The separate internal bridge token and administrator token are never consumer
credentials. Do not log request Authorization headers or dump environment/config.

There is no signup, billing, customer management, automatic token expiry, or
Keeper per-token quota/rate/concurrency cap. Upstream provider limits remain real.

## Request semantics

- `/v1/models` advertises the alias. `/v1/chat/completions` accepts OpenAI-shaped
  messages. The alias intentionally allows backend selection; its returned
  `model` is the actual selected backend model, not a quality guarantee.
- Rank is Coding Index among working compatible free routes; unmatched is
  unscored, never an invented Intelligence Index match. Upstream errors trigger
  exact feedback; same-model keys are preferred before weaker models, with at
  most three connection attempts and no failover after stream output.
- Native direct OpenAI backends accept safe standard chat fields, functions,
  response formats and streaming. Anthropic/Gemini/Responses translations reject
  features they cannot preserve. See `KEEPER_API.md` for the supported subset.
- The existing genuine OpenCode `zencli` bridge is a distinct verified transport.
  Plain string system/user/assistant messages retain its proven **flattened
  prompt-history** mapping, not lossless role semantics. It rejects tools,
  multimodal input, generation controls (`max_tokens`, temperature, etc.) and
  `stream:true`. Do not send these fields for the minimal text request, even
  empty `tools: []`. Direct richer backends remain eligible when available.
- Unsupported/paid extensions (`plugins`, built-in web search, alternate
  `models`, provider routing overrides) return 400 before inference. A request
  with no working compatible free backend returns an OpenAI-shaped 503, not a
  paid substitute or silently stripped features. A real stream failure after
  output emits a generic error and closes; clients must not treat it as complete.
- Malformed parameter values/message roles are rejected before selecting a key.
  Upstream HTTP 400/422 request rejections return a sanitized 400 without
  excluding healthy credentials or repeating that request across the key pool.
  Streaming checks retain incomplete credential prefixes across text/tool-argument
  chunks before release; ordinary output remains incremental.
- Do not automatically downgrade a coding-agent tool request to plain text: that
  changes user intent. Only explicitly text-only tasks should use text-only
  backend compatibility. Keeper is a model API, not a hosted autonomous agent.

## Operator boundaries

The dashboard and `/api/v2/*` require the administrator bearer or a scoped browser
session plus CSRF for mutations. They are not accessible with the service token.
Direct credentials are private, no-store responses and are verified for the exact
provider/key/model/route. Bridge-only success can make a key/owner working but is
labelled service-only and cannot be exported as a direct provider connection.

The **deployed CLI profile (frozen `83444b2`, not the original control)** isolates
OpenCode per request: exact selected credential in a 0600
private auth file, fresh HOME/XDG/config, scrubbed inherited environment, pinned
CLI v1.18.31, native build agent (no custom agent, tool/permission overrides,
or forced step limit), native ask policy with noninteractive auto-rejection,
immutable exact-`date` shell gate, no plugins/project config/default account,
exact provider/model whitelist and same free small model.
Only raw generated-text JSON events with a successful finish count as proof;
tool-only runs fail honestly without manufactured continuation.
The CLI task has no host mounts; it runs on Docker bridge (proven egress path)
with no published internal port, reaching Keeper only over authenticated Unix
HTTP IPC; timeout/process-group cleanup; unprivileged read-only sidecar
container. `--pure` alone is not a sandbox.
This profile is live-verified on production. Flaky fast-502s (~30%) and 110s
upstream stalls remain under characterization; see the README follow-ups.

## Verification status

Integrated live proof **established 2026-09-21, current production v15**
(keeper image `sha256:79da0139…`, zencli image `sha256:521fd0ae…`):
service-bearer `keeper-coder` currently serves `muse-spark-1.3-contributor-free`
(AA Coding 75.8, conservative max-variant mapping) over the genuine-CLI route;
canary exact-CLI observation WORKING + admin exact chat HTTP 200 (`big-pickle`,
`Monday, September 21, 2026.`); principal isolation 403/401s as specified;
canary DB leak scan 0 hits; pre-cutover availability backup retained;
migration to schema 3 applied cleanly. Verification economy: daily per-key
check budgets (5/day, oldest-first rotation) plus operator-forced discovery
refresh (admin-only, 1/hour) keep quota for serving. Still pending:
allocation-replacement durability proof and the parser/stall follow-ups in the
README. Never store credential values in receipts.

The dashboard distinguishes failed/pending inventory discovery from an empty
inventory, and shows per-key attempt/last-success timestamps and bridge failures.
Legacy mixed-transport responses use `evidence: exact_transport`; CLI success is
L2, never direct/L1 proof. Do not infer direct support from aggregate key health.

Optional offline browser regression (requires Playwright and a browser):
`node keeper/browser-smoke.cjs`. Set `PLAYWRIGHT_MODULE` and `CHROME_EXECUTABLE`
when using existing installations; screenshots/results go to a temporary folder
or `KEEPER_BROWSER_OUT`. Only synthetic fixtures are used, never live secrets.

See `docs/keeper-all-models-rollout.md` for topology, backup and rollback. The node
has no CNI bridge plugin; the approved, tested topology is Keeper on Docker host
networking (`127.0.0.1:8102`) plus the CLI sidecar on Docker bridge with no
published internal port, communicating over authenticated Unix HTTP IPC under
shared `/alloc/data`. No 8099 loopback listener exists anymore.

## Observability: metrics yes, logs yes, traces pending

- **Metrics**: live. `GET /metrics` (admin bearer) exposes route health
gauges; the `keeper-alloy` Nomad job scrapes every 30s into Grafana Cloud
(`meowlabs.grafana.net`), where the `keeper` folder holds the dashboard and
route/down/stale alerts. Verified end to end.
- **Traces**: half-wired. Instance `1470731`
  (`https://tempo-prod-25-prod-gb-south-1.grafana.net`), user `1470731`, token
  escrowed at Bao `secret/projects/nomad/GRAFANA_CLOUD_TRACES` (field `token`,
  `traces:write`, minted 2026-09-22). Keeper emits one stdlib OTLP span per
  non-health request (`keeper/tracing.py`, env-gated: `TEMPO_OTLP_USER` +
  `TEMPO_OTLP_TOKEN`, silent no-op when unset) and logs the W3C `trace-id`
  per request, so spans join to Loki lines. LIVE since v21: keeper posts
  spans to the local Alloy OTLP receiver (`127.0.0.1:14318`), Alloy exports
  via gRPC to `tempo-prod-25...:443` — direct OTLP/HTTP push 404s on this
  instance, the documented Alloy path is the one that works. Consumers:
  send a `traceparent` header and keeper joins your trace instead of
  minting one.
- **Logs**: live in Loki. The `keeper-alloy` job tails keeper containers via
  the Docker socket (`loki.source.docker`, matched on the task-first container
  name, static `service`/`project` labels) and pushes with the graph-engineering
  logs credential (`1476425` + Bao `secret/projects/graph-engineering/LOKI_SECRET`;
  the RW/RW2 tokens 401 on the push endpoint and ship nothing — verified live).
  Verify: `{service="keeper-server"}`
  (or `keeper-probe`) in Explore/datasource `grafanacloud-logs` returns fresh
  entries. Hard lessons, do not regress: Alloy River rejects `#` comments
  (use `//`); never labeldrop `__meta_docker_container_id` (ships zero lines
  with zero errors); container names are task-first, not job-first.
