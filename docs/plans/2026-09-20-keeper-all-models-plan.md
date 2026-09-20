# Keeper All-Models Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver the approved all-free-model/all-key check matrix, SQLite-backed status, verified direct provider credentials and feedback replacement through a private dark Keeper UI and API, deployed live.

**Architecture:** A dedicated availability/store service owns exact provider/key/model/API identities, durable observations and jobs, free discovery, verification and selection. Existing Python HTTP routing exposes additive authenticated APIs; the dark dashboard consumes the same state, with no network discovery on normal page reads. Legacy aggregate/CLI evidence never becomes direct API proof.

**Tech Stack:** Python stdlib (sqlite3, urllib, http.server, threading as needed), unittest/pytest, vanilla HTML/CSS/JS, Nomad/Docker and existing Bao secrets. No frontend framework or separate client integration.

**Binding specification:** `docs/plans/2026-09-20-keeper-all-models-design.md` (user approved).

## Working discipline

Single writer in `/Users/ksonny/git_projects/x-as-llm-api/wt/keeper-all-models`, branch `feat/keeper-all-models`, baseline `fd66590`. Do not touch sibling worktrees, unrelated files or secrets. Read local instructions. Graft was attempted and this repository is unindexed, so use scoped source search. Before changing signatures map callers with `rg` in this repository. Read UI UX Pro Max skill at `/private/tmp/pi-github-repos/runtime-iDUFDy/96f1ad21f3e2626b3f582719130d0b4bb9acf61f19d865b21d7bf7986c45077c/.claude/skills/ui-ux-pro-max/SKILL.md` and its relevant guidance; matched style is Data-Dense Dashboard, user selected dark.

For each task: write the smallest behavioral failing test; run and observe expected failure; implement minimal coherent code; rerun focused tests; commit that coherent slice. Do not invent free eligibility from a model name unless the provider formally defines that convention. Do not run inference with paid/unknown models to get a green result. Do not expose credentials via commands/logs/reports.

## Task 1 — Durable availability domain and exact identity

Files: create `keeper/availability.py`, `keeper/test_availability.py`; create `keeper/store.py`/`keeper/test_store.py` if separation improves the interface. Inspect `keeper/server.py` state/probe DB, `keeper/matrix.py`, `scripts/render-seeds.sh` and `probe/keyround.py` identities first.

1. Add failing tests for distinct provider/model identity, deduplicated credential identity across seeded models, two keys × three models = six independent records, any-success owner/key health, and 30-hour stale transitions. Include model B success not turning A green.
2. Run `(cd keeper && python3 -m pytest test_availability.py -q)` and capture red evidence.
3. Implement SQLite schema with versioned initialization, stable non-secret credential references, per-connection current observations plus check/feedback/selection history and persisted queue/cooldowns. Inject clock. Preserve existing database/table data; do not import ambiguous old successes. Transactions must handle later feedback versus earlier in-flight check races. Database errors cannot masquerade as successful updates.
4. Add/re-run restart/persistence, failed-sibling aggregation, absent owner, future timestamp, disabled/revoked and no-secret serialization tests.
5. Commit the passing domain slice.

## Task 2 — Free catalog and complete paced sweeps

Files: `keeper/inventory.py`, availability service, `keeper/test_inventory.py`, new domain tests; pricing/verification adapter module if warranted; `scripts/render-seeds.sh`; `probe/keyround.py` and tests only as required to stop contradictory evidence.

1. Add fixtures representing zero-price, paid, missing price, recurring free account tier, key-specific discovery, CLI-only credentials, provider failure and paginated model lists. Tests must prove every active eligible key is scheduled for every eligible provider model, including models beyond the old 20-column bound; no stop after the first success.
2. Run focused tests red, then implement discovery preserving free/access/protocol metadata. Prefer authoritative live model/pricing catalogs; support explicit provenance-bearing free metadata where provider APIs omit pricing. Unknown is visible and blocked, never treated as free. Do not classify all Gemini or Zen models free merely because their provider has some free models. Preserve last good inventory plus error/freshness on discovery failure.
3. Implement small real inference adapters for supported OpenAI/Anthropic/Gemini routes, validating nonempty generated text, provider errors within HTTP 200, exact returned model where required, correct request headers and output limits. No CLI evidence promoted to API success. Keep network injected for hermetic tests; returned client configuration must match successful probe transport.
4. Implement paced background worker and daily/manual sweep queue with durable progress, deduplication, overlap prevention, bounded retries, Retry-After handling and restart recovery. Manual checks cannot bypass cooldowns. Ordinary page reads only inspect state.
5. Test one rate-limited key does not lose other queued coverage, malformed/transient errors do not revoke a whole key, confirmed auth invalidity is key-wide, no paid probes, queue recovery and late observation protection. Commit passing slice.

## Task 3 — Selection, precise feedback and authenticated API

Files: `keeper/server.py`, availability/store modules, `keeper/test_server.py`, `keeper/test_availability.py`, `KEEPER_API.md`.

1. Write failing tests for freshest-success selection, five-minute revalidation, stale alternative verification, exact selected credential/model/protocol/endpoint, excluded/cooling key skipped, no working key error, report-and-replace staying on requested model, and persistent feedback after restart.
2. Implement one shared service used by UI and additive API (suggested `GET /api/v2/catalog`, `POST /api/v2/checks`, `POST /api/v2/credentials`, `POST /api/v2/feedback`; naming may follow existing conventions but document final wire contract). Stable connection IDs must target feedback; never fan one report/probe across unrelated credentials.
3. Protect all APIs with authentication. Enable narrowly scoped browser mutations via safe sessions with CSRF protection/origin validation, not a bearer embedded into HTML. Credential responses are no-store/private. Catalog/status/session bootstrap must not contain provider secret values. Avoid accepting arbitrary callback URLs or user-supplied upstream endpoints.
4. Keep legacy clients compatible and make legacy route/matrix behavior honest rather than leaving paths that advertise suspect keys as verified. Legacy raw-value pack APIs must not be claimed as verified selection. Do not rebuild a gateway.
5. Add HTTP integration tests covering unauthenticated rejection, cookie/bearer boundaries, forged cross-site requests, reflected malicious model/email text, error-body redaction and exact-identity feedback. Commit passing API slice.

## Task 4 — Coding Index and dark Accounts/Models dashboard

Files: `keeper/aa.py`, `keeper/test_aa.py`, `keeper/matrix.py`, `keeper/test_matrix.py`, `keeper/server.py`; new `keeper/dashboard.py` or static files as appropriate; `keeper/Dockerfile` to package new modules/assets.

1. Add failing tests for provider/model separation, working-unscored ahead of unavailable-scored, Coding Index only, missing/invalid score, conservative model matching, cached AA snapshot daily, and no external refresh during UI polling.
2. Implement rank and AA freshness with explicit alias support only when justified. Avoid old general-intelligence fallback. Keep prior usable snapshot on fetch failure, labelled stale.
3. Build dark accessible Accounts and Models tabs with search/provider filter, expanded per-key/model results/reasons/check times, progress, last sweep, Check all/Check key/Check model, verified token/config copy, report failure/get another, loading/error/empty/stale states. Match approved mockup, no green fabrication. Every free model stays visible; pagination must not drop coverage. No secrets in server-rendered initial page.
4. Test DOM/state behavior with local fake data including >20 models, more than one provider and key, mixed success/fail/stale/unknown, and malicious labels. Run browser QA/screenshots if tooling available at desktop and narrow viewport. Keep keyboard focus, button labels, safe responsive layouts and non-color-only statuses.
5. Commit passing UI/AA slice and update API/access docs to remove superseded behavior.

## Task 5 — Packaging, deployment preparation and full regression

Files: `keeper/Dockerfile`, `keeper.nomad.hcl`, `keeper/smoke.py`, `scripts/smoke.sh` as appropriate; deployment/verification doc under `docs/`.

1. Ensure new modules/assets are copied into image and daily scheduler starts once; build test verifies imports/runtime startup. Increase Nomad resources only based on observed need.
2. Prepare durable SQLite storage across allocation replacements using the actual cluster-supported host volume/bind pattern. Parent owns live deployment. Inspect cluster safely if authorized, but do not print secret-bearing job/seed responses. Back up existing data before migration; do not silently wipe it. Add safe rollout/rollback instructions and build identity.
3. Update smoke tests to exercise authentication, safe catalog, scheduling, credential selection (redact/never print key) and feedback against fake providers. Avoid destructive live feedback for healthy real credentials just to demonstrate fallback; use fixtures for failure injection.
4. Run `(cd keeper && python3 -m pytest -q) && (cd probe && python3 -m pytest -q) && (cd scripts && python3 -m pytest -q)`. Run packaging checks and diff/secret checks. Baseline is 149+46+11 tests, all green when run from each folder.
5. Fresh independent review: correctness/coverage and security/UI/deployment readiness. Fix concrete defects and rerun affected suites before parent accepts. Supply changed files/commits, red-green proof, commands, contract checklist, unresolved operational risks and exact deployment instructions. Do not claim production success from local tests.

## Task 6 — Parent-controlled live rollout and evidence

1. Inspect final diff and independent review evidence. Build/publish exact reviewed image using existing registry credentials without logging values. Validate and plan the Nomad job with existing secrets kept in memory or mode-0600 temporary files.
2. Back up state, mount durable store, deploy only Keeper-related jobs/config needed for the approved checks. Preserve unrelated services and existing secrets. Prevent legacy periodic probes from overwriting new exact evidence or unnecessarily duplicating checks.
3. Verify public health, authenticated dark dashboard/catalog/accounts, unauthorized secret rejection, deployed build identity and database persistence. Start the complete free matrix sweep; record key/provider/model coverage, pending cooldowns and classified outcomes with no secrets.
4. Retrieve a verified provider credential inside a redacting process and use its matching advertised connection for real inference. Verify multiple models/providers when actually available, never assert that every provider works. Token values must not appear in tool transcripts, artifacts or shell history.
5. Record honest live verification receipts and remaining unavailable models/providers. Refresh evidence after fixes. Completion requires deployed behavior and coverage, not merely a working Big Pickle example.
