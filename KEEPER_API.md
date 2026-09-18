# KEEPER_API — v2 (`keeperPackVersion: v2`)

One-way contract: pi-infinity-llm pins this; keeper never imports from it.
Changes are additive + version-bumped.

Auth: `Authorization: Bearer $KEEPER_TOKEN` on everything except
`GET /healthz` ( else `401`). Rotation window: `KEEPER_TOKEN_NEXT`, when
set, is accepted alongside `KEEPER_TOKEN` (parallel-accept); unset it to
revoke. Seeds come from `SEED_FILE` JSON
(`{"routes": [...]}`); production seeds export live Bao refs
(`secret/projects/pi-multi-providers/<NAME>`, excluding
`*_UNAVAILABLE/*_RETIRED/*_INACTIVE/*_BANNED` markers).

| Method & path | Auth | Status |
|---|---|---|
| `GET /healthz` | none | `200` → `ok` |
| `GET /packs` | bearer | frozen snapshot `{keeperPackVersion, packs[]}`; `ETag`/`304`, `Cache-Control: max-age=600` |
| `POST /feedback` | bearer | `202` spool to JSONL; `422` with `missing[]` / `bad_errorClass` |
| `POST /api/v1/probe` | bearer | ingest one probe_route result `{provider, model, state, detail{l1,l2}, checkedAt?}` → `202` (records probe_detail + probe state, busts matrix cache); `422` shape/unknown-route |
| `GET /v1/providers` | bearer | per provider: `baseURL`, `modelIDs[]`, `envVar`, ready OpenAI `curl` |
| `GET /v1/guide/:who` | bearer | `who` in `curl\|pi\|opencode`; one OpenAI curl per model |
| `POST /v1/chat/completions` | bearer | OpenAI-in/out on either upstream wire; `stream: true` → SSE `data:` chunks + `[DONE]` |
| `GET /v1/models` | bearer | OpenAI `{object: list, data[]}` over seeded models |
| `GET /v1/route/:model` | bearer | `{model, baseURL, api: "openai", auth: {scheme, value}, features, keeperPackVersion}`; `404` unknown |
| `GET /api/v1/matrix` | bearer | `{emails, rows, providers, diagnostics: {unassigned, skippedInactive}}`; `?refresh=1` bypasses cache |
| `GET /api/v1/accounts` | bearer | `{emails, unassigned_count}` |
| `GET /api/v1/health` | bearer | `{ok, keeperPackVersion, routes}` |
| `GET /metrics` | bearer | Prometheus text: `keeper_route_divergent{provider,model,connection}` 0/1 (L1-fail+L2-pass) + `keeper_probe_checked_at_seconds`; series only for dual-probed connections |
| `GET /` | bearer | server-rendered matrix table + `diagnostics.unassigned` (values never in HTML) |
| `GET /guides` | bearer | per-consumer copy-paste cards |
| `GET /signin` | bearer | re-mint steps for keyless members |
| `GET /report` | bearer | feedback form posting to `/feedback`, shows live route state |

Member shape: `{provider, model, base_url, env_var}` plus
`credential: {type: "bearer", value}` when a live credential exists,
else `signin: {steps[]}`.

Feedback fields (all required): `provider`, `model`, `errorClass`
(`auth|upstream_5xx|unknown|limited|misconfigured|denied|timeout`),
`httpStatus`, `keeperPackVersion`. Any report flips the route to `suspect`.
