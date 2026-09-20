# Engineering guidance: consuming Keeper

**Candidate contract, not yet live:** the private OVH staging run was blocked by
upstream rejection/rate limits and has been stopped. Production is unchanged;
see [staging evidence](keeper-staging-2026-09-20.md). Do not switch consumers yet.

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

OpenCode execution is isolated per request: exact selected credential in a 0600
private auth file, fresh HOME/XDG/config, scrubbed inherited environment, pinned
CLI v1.18.31, dedicated agent with all tools denied, one step, no plugins/project
config/default account, exact provider/model whitelist and same free small model.
Only raw generated-text JSON events with a successful finish count as proof.
No host data mounts; internal loopback bearer mandatory; timeout/process-group
cleanup; unprivileged read-only sidecar container. `--pure` alone is not a sandbox.

## Verification status

Fresh integrated live proof is **pending parent rollout**, not established by
local tests. Parent must record reviewed build IDs, successful authenticated
public API inference, actual selected transport, safe stream/tool results where
supported, full key/model coverage including failures/cooldowns, and durable DB
survival across allocation replacement. Never store credential values in that
receipt. Historical CLI receipts establish feasibility only.

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
