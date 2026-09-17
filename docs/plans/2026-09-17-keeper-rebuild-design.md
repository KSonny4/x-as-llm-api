# Keeper Rebuild — Design (approved 2026-09-17)

All six sections approved by owner in brainstorming review. Full rebuild (option C).

## Principles (locked)

- **E2E first, always — against Nomad, not localhost.** First deployable slice (healthz + packs) goes to Nomad immediately; breadth is added only on top of a live deployment. Local-only curls are never sufficient evidence: every phase gate replays the same curls against the Nomad URL. (Also recorded in engineering-guidance as a standing principle.)
- **Deployed baseline 2026-09-17:** `/healthz` 200; `/packs` no-bearer → 401, garbage bearer → 401, Bao-stored `KEEPER_TOKEN` → **403** (differs from server.py's 401-only logic — OPEN: reconcile/rotate token with deploy owner before v2 reads depend on it).
- **Origin UNPROVEN:** Coolify project `keeper` (uuid `pp7eq33nlgkszotau67p2eym`) + app `keeper` (uuid `kv4gvawhgshjaxdggb2vgvuf`) exist, but the recorded first deploy FAILED (private-repo clone); no success recorded since. Cloudflare masks origin (all hosts show `server: cloudflare`), so outside probing cannot distinguish Coolify vs Nomad vs manual. OPEN (owner): check Coolify dashboard deployments for the app uuid; whatever serves the hostname today is deprecated in favor of the Nomad v2 job, then the Coolify app is removed.

## §1 — Repos: two, one contract (REVISED, approved)

- **`KSonny4/x-as-llm-api` = this folder = the keeper.** Keeper service (values API,
  curl/pi/opencode guides, quota-matrix UI, feedback), L1/L2 probe worker, compose,
  docs. No extension code — only the versioned **`KEEPER_API.md`** contract.
- **`KSonny4/pi-infinity-llm` = rebuilt minimal = the extension.** Canonical source is the `pi-multi-providers` working tree (it carries the Zen-mint + `x-api-key` mirroring fix). Strip to
  extension-only: `extension/` (v2 values-mode keeper extension), its tests, minimal
  README pointing at x-as-llm-api. Old material (`keeper/`, `packs/`, `prototype/`,
  keeper-spec docs, old e2e) snapshotted to `archive/pre-split` branch, then deleted
  from `master`.
- **Dependency is one-way.** Extension pins minimum `keeperPackVersion` from
  `KEEPER_API.md`; keeper never imports from the extension repo. Contract changes are
  additive + version-bumped; breaking changes get a new `keeperPackVersion` served in
  parallel until cutover is proven.
- **Deploy target is Nomad, not Coolify.** Prod runs as a Nomad job (`keeper.nomad.hcl` in this repo); `compose.yaml` is local-dev only. Secrets reach the alloc from Bao (NomadSetup acl/registry; exact stanza at build time). The old Coolify path dies with the old keeper — no Coolify work in v2.
- **`KSonny4/llm-quota`** (read-only OmniRoute quota matrix): full deprecation after
  matrix parity (ported `matrix.test.js` green). `DEPRECATED.md` + hostname move +
  archive. `pi-multi-providers/` is not a repo (remote = pi-infinity-llm) — covered
  by that deprecation.

## §2 — Keeper API: values + sign-in guidance (approved)

- Auth: `Authorization: Bearer $KEEPER_TOKEN` on everything except `GET /healthz`.
  Values endpoints additionally require TLS.
- `GET /packs` keeps frozen-snapshot shape (`keeperPackVersion`, `ETag`/`304`,
  `max-age=600`) but members carry `credential: {"type":"bearer","value":"…"}` or
  `signin: {…}` guidance when no live credential exists (exact re-mint commands).
- `GET /v1/providers`: per working provider — `baseURL`, `modelIDs[]`, `envVar`,
  ready curls. `GET /v1/guide/curl|pi|opencode`: copy-paste snippets generated from
  live probe state, never hand-edited.
- `POST /feedback` (`202` spool to JSONL, required v2 fields incl. `errorClass`,
  `httpStatus`, `keeperPackVersion`): any report flips the route to `suspect` and
  triggers an immediate probe.

## §2 addendum — OpenAI-out translation, full parity (approved, REVISED)

- Curl consumers speak only OpenAI. Keeper exposes standard OpenAI paths —
  `POST /v1/chat/completions` (incl. `stream: true` SSE), `GET /v1/models`,
  OpenAI-shaped errors — regardless of upstream wire.
- Translator inside the keeper (`keeper/translate.py`, fixture-tested): `wire:
  openai` passes through; `wire: anthropic` translates both ways (OpenAI
  request → Anthropic `/v1/messages` → OpenAI `choices` incl. tool_calls, usage,
  SSE chunks). `wire` is internal-routing-only in `KEEPER_API.md`.
- Parity = chat completions + streaming + tool calls + models + standard errors.
  NOT in v2: embeddings, audio, images, assistants, batch (YAGNI).
- Dispenser emits one OpenAI curl per model. Seed defaults: Muse-family →
  `openai`; Alpha/union → `anthropic`; probe verifies wire per route,
  wrong-wire is `misconfigured`, not `down`. Only two wires in v2.

## §2 addendum — Machine route interface (approved)

- Consumers prepare for exactly one interface: OpenAI. Translation lives in
  `keeper/translate.py`, not in every consumer.
- `GET /v1/route/:model` (bearer-authed JSON): `{ model, baseURL, api:
  "openai", auth: { scheme: "bearer", value: "…" }, features:
  ["chat","stream","tools"], keeperPackVersion }`. Services fetch at startup,
  speak plain OpenAI chat/completions, never hardcode keys/URLs.
- Lifecycle mirrors the extension: cache, re-fetch on 401/403, refresh on
  `keeperPackVersion` change. Copy-paste Python (`urllib`) + Rust (`reqwest`)
  sketches ship in `/guides`. Values only to bearer-authed callers over TLS;
  one team token in v2 (known limitation).

## §3 — Quota-matrix UI in keeper, deprecates llm-quota (approved)

- `GET /` (server-rendered HTML, stdlib only) + `GET /api/v1/matrix|accounts|health`
  with llm-quota semantics: rows = owner emails (email field → email-in-name
  fallback, case-insensitive dedupe), columns = distinct providers,
  `diagnostics.unassigned` + `skippedInactive`, `?refresh=1` bypass.
- Data: probe states only — no OmniRoute join. Rows/cols/diagnostics keep llm-quota semantics (owner-email rows, provider cols, `unassigned` + `skippedInactive`), cells colored from probe state (`ok/degraded/suspect/down`). Never invent quota numbers.
- Ranking: probes decide working/best; Artificial Analysis orders quality ties among probe-ok models only (snapshot via `ARTIFICIALANALYSIS_API_KEY`, refreshed daily, last-good retained). No pack frontiers, no billing logic.

## §4 — pi-keeper extension v2: values mode + keep-alive (approved)

- Session-prefetch `GET /packs` (bearer), per-request injection from served values
  (TTL cache, never logged/disk). `CONNECTION_KEY_ENV` local-env resolution deleted.
- TTL + skew refresh, `ETag`/`304`, 401/403 → drop + refetch, stale-serve offline.
  `pi+meta` OAuth refresh stays extension-owned; `signin` members surface the exact
  re-mint command. Zen per-request mint carried over. Feedback spool
  (`~/.pi/agent/keeper-feedback.log`) extended to v2 fields, flushed to
  `POST /feedback`.

## §4 addendum — Rust helper binary `keeper-helper` (approved)

- Tiny Rust CLI (`cargo build --release`, single binary, `helper/` in extension
  repo), spawned over stdio by the TS extension (pi loads TS only).
- Subcommands, JSON stdin/stdout, no secrets on argv:
  `mint-zen-session` (replaces vendored `zen_mint.py` port — exact `u64` math),
  `sign` (request headers from a served credential), `shape` (probe/feedback JSON
  normalization, kills remaining Python).
- No NAPI, no daemon by default; promote to persistent JSON-lines process only on
  measured spawn-latency evidence.

## §5 — Validation: L1 curl → L2 opencode CLI + feedback (approved)

- Probe worker (keeper image, second command; 5-min loop + on-demand): L1 = curl
  (`GET /models` 200 + non-empty, tiny `ping` chat returns text). L2 = only on L1
  failure: `opencode run --pure -m <provider/model> "ping"`. L2-pass ⇒ `degraded`
  (route wrong, provider alive); L1+L2-fail ⇒ `down`.
- States: `ok` → `suspect` (report or single miss + instant re-probe) → `down`/`ok`.
  HTTP 429 ⇒ `limited` (backoff, route kept, retry-clock shown) — never confused
  with deny. Auth-shaped denial ⇒ `down`/`suspect` + feedback event.
  Served as `status.json`; matrix colors from it. Reports carry refs only, never keys.
- Cutover rollback is smoke-gated + rehearsed: flip `KEEPER_BASE_URL` + version pin;
  red `smoke.sh` or a user report within 24h flips it back.

## §6 — Keeper UI: minimal, server-rendered (approved)

- `/` matrix, `/guides` per-consumer copy-paste cards (same data as
  `GET /v1/guide/:who`), `/signin` re-mint steps, `/report` feedback form showing
  live route state. Read-only + report only; no key editing/rotation; values never
  render into HTML.

## Decisions log

| # | Question | Answer |
|---|----------|--------|
| 1 | Credential delivery | Keeper serves values to authed extension |
| 2 | x-as-llm-api role | The keeper (this folder) |
| 3 | opencode sanity check | CLI probe (`opencode run --pure`) |
| 4 | Approach | C. Full rebuild |
| 5 | Rust scope | Helper binary (mint/sign/shape) |
| 6 | llm-quota | Absorbed minimal matrix, deprecate |
| 7 | pi-infinity-llm | Rebuild minimal, extension-only (canonical: pi-multi-providers tree) |
| 8 | Matrix source | Probes only, no OmniRoute; AA orders ties among probe-ok |
| 9 | Seed source | Bao `projects/pi-multi-providers/` live refs (seed everything; exclude `*_UNAVAILABLE/*_RETIRED/*_INACTIVE/*_BANNED` markers); `KEEPER_TOKEN` reused from Bao, not re-minted |
| 10 | Failure policy | 429 ⇒ limited+backoff; deny ⇒ down/suspect; rollback smoke-gated + rehearsed |
| 11 | Gates | Phase gates + live proof (units + smoke + real inference per phase) |
| 12 | Runnable goal | Keeper-first slice (Tasks 0–6d) through Nomad cutover; extension/matrix/probes deferred |
| 13 | Token 403 | Agent authorized to rotate/reconcile KEEPER_TOKEN |

## Out of scope (explicit)

NAPI/daemon, Vite split, key rotation UI, full AA packs/catalog/rotation (tiebreak only), OpenAI-compatible
`/v1/chat` proxy (revisit only if dispenser proves insufficient).
