# KEEPER_API — v2 (`keeperPackVersion: v2`)

One-way contract: pi-infinity-llm pins this; keeper never imports from it.
Changes are additive + version-bumped.

Auth: `Authorization: Bearer $KEEPER_TOKEN` on everything except
`GET /healthz` and `GET /login` ( else `401`). Rotation window: `KEEPER_TOKEN_NEXT`, when
set, is accepted alongside `KEEPER_TOKEN` (parallel-accept); unset it to
revoke. Browser login: `POST /api/v1/session` (bearer) mints a 12h
`keeper_session` cookie (`HttpOnly; Secure; SameSite=Lax`); the cookie is
accepted for GET pages only — POSTs stay bearer-only — and dies with
restarts (in-memory). Token travels in the mint fetch header, never URL. Seeds come from `SEED_FILE` JSON
(`{"routes": [...]}`); production seeds export live Bao refs
(`secret/projects/pi-infinity-llm/<NAME>`, excluding
`*_UNAVAILABLE/*_RETIRED/*_INACTIVE/*_BANNED` markers).

| Method & path | Auth | Status |
|---|---|---|
| `GET /healthz` | none | `200` → `ok` |
| `GET /packs` | bearer | frozen snapshot `{keeperPackVersion, packs[]}`; `ETag`/`304`, `Cache-Control: max-age=600`; one standalone pack per model with `path: infinity/<provider>/<model>`; inventory-only models get signin packs |
| `POST /feedback` | bearer | `202` spool to JSONL; `422` with `missing[]` / `bad_errorClass` |
| `POST /api/v1/probe` | bearer | ingest one probe_route result `{provider, model, state, detail{l1,l2}, checkedAt?, connection_id?}` → `202` (records probe_detail + probe state per connection — `connection_id` targets one spare, omitted fans out to all same-model routes; busts matrix cache); `422` shape/unknown-route/unknown-connection. Probe L1 wires: `openai` (`/models` + chat ping), `anthropic` (`/v1/messages` ping), `gemini` (`generateContent` ping); L2 is the opencode CLI leg on the route provider/model ref. |
| `GET /v1/providers` | bearer | per provider: `baseURL`, `modelIDs[]`, `envVar`, ready OpenAI `curl` |
| `GET /v1/guide/:who` | bearer | `who` in `curl\|pi\|opencode`; one OpenAI curl per model |
| `POST /v1/chat/completions` | bearer | OpenAI-in/out on either upstream wire; `stream: true` → SSE `data:` chunks + `[DONE]` |
| `GET /v1/models` | bearer | OpenAI `{object: list, data[]}` over seeded models |
| `GET /v1/route/:model` | bearer | `{model, baseURL, api: "openai", auth: {scheme, value}, features, keeperPackVersion}`; `404` unknown |
| `GET /api/v1/matrix` | bearer | `{emails, rows, providers, diagnostics: {unassigned, skippedInactive}}`; columns keyed per model (`providers[]: {id, provider, model, probed}`); `?refresh=1` bypasses cache and re-enumerates provider inventory (1h server TTL). Inventory source: per-provider live APIs (OpenAI-compatible `/models`, Gemini list) with per-provider degrade to seed-declared; unlistable providers (OAuth/CLI-only) are seed-declared. Inventory-only columns capped at 20 per provider, overflow in `diagnostics.inventory_more` (full list always in packs). |
| `GET /api/v1/accounts` | bearer | `{emails, unassigned_count}` |
| `GET /api/v1/health` | bearer | `{ok, keeperPackVersion, routes}` |
| `GET /metrics` | bearer | Prometheus text: `keeper_route_divergent{provider,model,connection}` 0/1 (L1-fail+L2-pass) + `keeper_probe_checked_at_seconds`; series only for dual-probed connections |
| `GET /` | bearer or session cookie (GET only) | server-rendered matrix table + `diagnostics.unassigned` (values never in HTML); 30s just-in-time poller of `matrix?refresh=1` with stale banner; standard state colors + divergent badges + legend; opening a provider shows only `ok` model columns sorted by AA score desc (unscored last, `aa_stale` badge when scores are stale) — display-only, JSON keeps every column |
| `GET /guides` | bearer | per-consumer copy-paste cards |
| `GET /signin` | bearer | re-mint steps for keyless members |
| `GET /login` | none | public token form; POSTs bearer via fetch, redirects to `/` |
| `POST /api/v1/session` | bearer (never cookie) | mint browser session → `200 {ok:true}` + `Set-Cookie`; `401` mints nothing |
| `POST /api/v1/session/logout` | session cookie or bearer | clear session → expiring `Set-Cookie` |
| `GET /report` | bearer | feedback form posting to `/feedback`, shows live route state |

Member shape: `{provider, model, base_url, env_var}` plus
`credential: {type: "bearer", value}` when a live credential exists,
else `signin: {steps[]}`.

Feedback fields (all required): `provider`, `model`, `errorClass`
(`auth|upstream_5xx|unknown|limited|misconfigured|denied|timeout`),
`httpStatus`, `keeperPackVersion`. Any report flips the route to `suspect`.

## Authoritative v2 availability API (2026-09-20)

Legacy packs and `/v1/route/*` are **raw, unverified configuration**, not
verified credentials. They require an administrator bearer, never a browser
cookie, and are non-cacheable. Legacy probe/CLI results are not v2 proof.

All v2 requests require the administrator bearer or a private login session.
Browser POSTs additionally require `Origin` equal to configured `PUBLIC_ORIGIN`
and `X-Keeper-CSRF` from `GET /api/v2/session`. The Keeper bearer is not stored
in browser storage or page source. The session cookie is Secure/HttpOnly.

- `GET /api/v2/catalog`: local-only models, exact connections, keys/owners,
  coverage, latest sweep, discovery errors, Coding Index freshness. No secrets.
- `POST /api/v2/checks`: `{}` checks all; optional `credential_id` and/or
  `model_id` scope the persisted paced queue. Returns 202 progress.
- `POST /api/v2/credentials`: `{"model_id":"<catalog id>"}` returns an actual
  verified upstream `api_key`, `headers`, `base_url`, `endpoint`, `protocol`,
  exact `model`, `provider`, `connection_id`, `model_id`, `verified_at`.
  Freshest success wins; older than five minutes is reverified. Up to three
  attempts, each bounded by upstream timeout; cooldown/pacing cannot be bypassed.
- `POST /api/v2/feedback`: `{"connection_id":"<returned id>","reason":"client_failure"}`
  excludes only that connection and queues verification. Returns a freshly
  verified alternative for the **same model identity**, never another model.
  Reasons are a fixed classification, not arbitrary diagnostic text.

Selection/replacement returns 409 with `no_working_connection` or
`verification_pending` when no verified candidate can be returned. Unknown
identities return 404; malformed/unrecognized fields return 422. Responses are
`Cache-Control: no-store, private`. No user-supplied upstream endpoints accepted.

Coding Index uses exact AA slugs only (no Intelligence Index or guessed suffix
match). Missing scores remain unmatched. Daily refresh retains the last usable
snapshot on failure, marked stale; catalog polling never fetches providers/AA.

## Service-to-service inference (latest approved scope amendment)

The separate, manually issued `KEEPER_SERVICE_TOKEN` is **non-expiring** and
inference-only. Parent provisions it in Bao; never put it in frontend code.
No Keeper usage quotas, token rate/concurrency caps or automatic expiry apply.
Upstream quota/cooldowns, pricing freshness and free eligibility still apply.
Base URL: `https://keeper.pkubelka.cz/v1`; model: `keeper-coder`.

Only `GET /v1/models` and `POST /v1/chat/completions` accept this principal.
All dashboard, raw packs, admin diagnostics, checks, feedback and actual-provider
credential endpoints return 403 to it. Administrator credentials remain separate.

`keeper-coder` explicitly opts into highest Coding Index **verified working,
compatible, free** route across all providers, not a claim of globally strongest.
If no scored compatible route is working, unscored working routes are eligible.
Background checks establish availability; the service never spends on unknown
pricing or paid routes. Actual upstream failure records precise feedback, and
up to three connection attempts may be made, preferring same-model alternative keys before a lower-ranked model before returning an OpenAI-shaped 503.
No fallback occurs after any stream output. SSE comes incrementally from the
upstream, not a buffered nonstream response. Tool calls/history are preserved.

Native OpenAI routes accept an explicit safe chat-field allowlist. Paid plugins/built-in tools, alternate model lists and provider/routing overrides are rejected with 400, even on free models. Unknown extensions are never forwarded. Text and client function tools are supported; paid image/audio/search add-ons are not. Anthropic, Gemini and Responses
routes translate text and function-tool history/calls, max output tokens,
temperature/top-p and tool choice. Anthropic/Gemini also map stop sequences.
Translated routes are skipped for unsupported features (e.g. multimodal content,
strict tool schemas, response_format, parallel_tool_calls, n, or usage-inclusive
stream_options); these are never silently discarded. Responses cannot map stop
sequences. A request with no working compatible route gets 503. Returned `model`
identifies the actual backend, while private `/api/v2/credentials` always stays
on its requested exact model identity.

### Legacy migration safety

Production `/api/v1/matrix`, `/api/v1/health` and `/api/v1/key-queue` now read
v2 exact direct evidence, never baked CLI success. Probe ingest without
`connection_id` is accepted only for a unique route; multi-key fanout is rejected.
Legacy diagnostic/feedback bodies are reduced to bounded classifications before
persistence. They never become direct v2 proof; use v2 precise feedback to
exclude a credential connection.

Administrator `/v1/chat/completions` retains explicit model requests, but in the
production runtime these also require verified free availability and honest
Keeper transport identity (no OpenCode CLI impersonation). A unique exact model
name or catalog `model_id` selects that route only; ambiguous names require the
catalog ID. Explicit requests can retry keys for that route, never another model.
An upstream free-tier rule restricting use to its own CLI remains access denied.

### Genuine Zen CLI backend (latest user-approved correction)

The existing proven `zencli` bridge is reused as a distinct service backend.
Its `protocol: zencli` connection identities are derived dynamically from the
same fresh authoritative free catalog and checked with the exact selected key
and model. CLI success is never imported into a direct HTTP connection.
`/api/v2/credentials` returns 409 `not_exportable` for these identities; catalog
labels them service-only. Actual-key export remains direct-verification-only.

This backend accepts plain string system/user/assistant messages via the existing
flattened prompt mapping. It rejects tools, generation controls (including
`max_tokens`), multimodal input and `stream:true`; no buffered SSE masquerades as
real streaming. `keeper-coder` includes it only for compatible text requests.
The authenticated private bridge has no static model cap/default account and is
never accessible to the public service bearer. Execution isolation and pinned
CLI configuration proof are documented in `zencli/README.md`.

Priced OpenRouter/Kilo catalogs require authoritative **text-only output** plus
text input modalities before zero token rates establish free eligibility. Mixed
text+audio Lyria entries remain visible with unknown eligibility: their zero
text-token rates do not cover documented per-song/clip charges. Missing modality
evidence is also blocked, including on partial discovery refreshes.


### Transport policy and native CLI repair (schema 2)

See [repair/canary/migration evidence](docs/keeper-transport-repair.md).
Free Zen direct identities remain visible as `cli_required`; their history is
retained but no direct inference checks, selection or credential export run.
Genuine CLI routes remain separately checked with every eligible exact key/model.
Other providers' supported transports are unchanged.

Upstream cooldown/auth-invalid scope is exact credential + endpoint + protocol;
manual revocation/disabled status and credential generations remain global.
Catalog connections expose `cooldown_scope`: `exact_transport` or the conservatively
retained `legacy_scope_unknown`. CLI 429/Retry-After is a real CLI cooldown, not a
reason to probe a futile direct Zen route. No Keeper customer quota is introduced.

Native build tools remain defined but permission requests are auto-rejected by
pinned noninteractive OpenCode (never approval flags). No custom agent or forced
step count. Tool-required runs without final text fail honestly. This does **not**
make CLI-only routes compatible with ordinary tool-using or streaming agents.


### Current Unix IPC / exact native clock correction (schema 3)

CLI connections use logical authority `http://keeper-zencli/v1` over authenticated
private Unix HTTP, not DNS/TCP. Historical loopback IDs are not selectable and do
not confer success on new IDs. Active evidenced prior CLI policy may be retained
with `policy_source: "inherited prior CLI endpoint"` and its source base URL;
`cooldown_scope: "inherited_prior_cli_endpoint"` is a scheduling policy, not a
new observation. Direct HTTP limits are never copied to this CLI policy.

Native ask-only was insufficient for raw shell syntax. An immutable gate now
permits only exact internal `date`, executing `/bin/date` without an interpreter,
with scrubbed UTC/C environment. Missing gate is fatal. Actual successful clock
execution plus subsequent model final text is required; no tool output or
continuation is fabricated. Consumer capabilities stay plain-history-only, not
generic tools/streaming. See [security/canary gate](docs/keeper-uds-clock-repair.md).
