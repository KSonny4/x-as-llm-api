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
