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

The **current modified candidate, not the successful original control**, isolates
OpenCode per request: exact selected credential in a 0600
private auth file, fresh HOME/XDG/config, scrubbed inherited environment, pinned
CLI v1.18.31, dedicated agent with all tools denied, one step, no plugins/project
config/default account, exact provider/model whitelist and same free small model.
Only raw generated-text JSON events with a successful finish count as proof.
No host data mounts; internal loopback bearer mandatory; timeout/process-group
cleanup; unprivileged read-only sidecar container. `--pure` alone is not a sandbox.
This deployed profile is live-verified: canary exact RETIRED_1/big-pickle/date
HTTP 200s via the native build agent with ask policy plus the immutable
exact-date gate (no custom agent, tool/permission overrides, or forced step
limit — same shape as the successful original, plus the proven egress and IPC
changes). Flaky fast-502s (~30%) and 110s upstream stalls remain under
characterization; see the README follow-ups.

## Verification status

Integrated live proof **established 2026-09-21 on production v12** (frozen
`83444b2`; keeper image `sha256:84cbc9d5…`, zencli image `sha256:521fd0ae…`):
service-bearer `keeper-coder` chat HTTP 200 (`PROD-SVC-OK` via
`inclusionai/ling-3.0-flash-vl:free`); canary exact-CLI observation WORKING +
admin exact chat HTTP 200 (`big-pickle`, `Monday, September 21, 2026.`);
principal isolation 403/401s as specified; canary DB leak scan 0 hits;
pre-cutover availability backup retained (schema-1 snapshot); migration to
schema 3 applied cleanly on production. Production CLI rows verified working
(big-pickle + ling-fin + muse-spark across keys; muse-spark ranked first at
75.8 and served). Still pending: allocation-replacement durability proof and
the parser/stall follow-ups in the README. Never store credential values in
receipts.

The dashboard distinguishes failed/pending inventory discovery from an empty
inventory, and shows per-key attempt/last-success timestamps and bridge failures.
Legacy mixed-transport responses use `evidence: exact_transport`; CLI success is
L2, never direct/L1 proof. Do not infer direct support from aggregate key health.

Optional offline browser regression (requires Playwright and a browser):
`node keeper/browser-smoke.cjs`. Set `PLAYWRIGHT_MODULE` and `CHROME_EXECUTABLE`
when using existing installations; screenshots/results go to a temporary folder
or `KEEPER_BROWSER_OUT`. Only synthetic fixtures are used, never live secrets.

See `docs/keeper-all-models-rollout.md` for topology, backup and rollback. The node
has no CNI bridge plugin; the approved, tested topology is Docker host networking,
with Keeper on `127.0.0.1:8102` and zencli on `127.0.0.1:8099`. Both are private
loopback listeners. The latter is never exposed through the public tunnel.
