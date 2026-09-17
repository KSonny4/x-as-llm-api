# Keeper Rebuild — Design (approved 2026-09-17)

All six sections approved by owner in brainstorming review. Full rebuild (option C).

## §1 — Repos: two, one contract (REVISED, approved)

- **`KSonny4/x-as-llm-api` = this folder = the keeper.** Keeper service (values API,
  curl/pi/opencode guides, quota-matrix UI, feedback), L1/L2 probe worker, compose,
  docs. No extension code — only the versioned **`KEEPER_API.md`** contract.
- **`KSonny4/pi-infinity-llm` = rebuilt minimal = the extension.** Strip to
  extension-only: `extension/` (v2 values-mode keeper extension), its tests, minimal
  README pointing at x-as-llm-api. Old material (`keeper/`, `packs/`, `prototype/`,
  keeper-spec docs, old e2e) snapshotted to `archive/pre-split` branch, then deleted
  from `master`.
- **Dependency is one-way.** Extension pins minimum `keeperPackVersion` from
  `KEEPER_API.md`; keeper never imports from the extension repo. Contract changes are
  additive + version-bumped; breaking changes get a new `keeperPackVersion` served in
  parallel until cutover is proven.
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

## §2 addendum — Per-model wire compatibility (approved)

- Wire is per-model, not per-gateway. Each route carries
  `wire: "openai" | "anthropic"` (persists `freeze_map.json` api/targetFormat
  knowledge). Router branches: `openai` → `POST {baseURL}/chat/completions`;
  `anthropic` → `POST {baseURL}/v1/messages` (Anthropic headers/body).
- Seed defaults: Muse-family → `openai`; Alpha/union → `anthropic`. Probe verifies
  the wire per route; wire-mismatch is classified distinctly from down.
- Dispenser emits the correct curl per model (chat/completions vs v1/messages
  with `x-api-key` + `anthropic-version`). Extension Bearer→`x-api-key` mirroring
  for anthropic-messages transports is contract (`KEEPER_API.md`).
- Only two wires in v2 (`openai-responses` legs map to `openai` unless a probe
  proves otherwise).

## §3 — Quota-matrix UI in keeper, deprecates llm-quota (approved)

- `GET /` (server-rendered HTML, stdlib only) + `GET /api/v1/matrix|accounts|health`
  with llm-quota semantics: rows = owner emails (email field → email-in-name
  fallback, case-insensitive dedupe), columns = distinct providers,
  `diagnostics.unassigned` + `skippedInactive`, `?refresh=1` bypass.
- Data: probe results joined with OmniRoute management API where configured
  (`OMNI_BASE_URL` + manage-scope key); without it, matrix renders from keeper probe
  state with a "quota depth unavailable" banner. Never invent quota numbers.
- YAGNI: no AA ranking, packs/catalog, or rotation come over.

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
  Served as `status.json`; matrix colors from it. Reports carry refs only, never keys.

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
| 7 | pi-infinity-llm | Rebuild minimal, extension-only |

## Out of scope (explicit)

NAPI/daemon, Vite split, key rotation UI, AA ranks/packs, OpenAI-compatible
`/v1/chat` proxy (revisit only if dispenser proves insufficient).
