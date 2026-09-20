# Keeper: every free model, every key

Status: APPROVED by the user in the 2026-09-20 interview ("Approve and implement").
This contract supersedes conflicting historical display-only/ok-only/big-pickle-specific requirements. Existing clients remain compatible where possible; new capabilities use additive versioned APIs. No separate client repository changes are in scope.

## Objective

Keeper must check every active stored credential against every eligible free model at its provider, show exact results, mark its owner working if ANY key/model works, and provide an actual verified provider credential for ANY requested free model. Big Pickle has no privileged role: all model checks, selection, feedback and display are generic.

## Settled decisions

- Free = zero-price models plus recurring free allowances. No intentional paid balance spending; trial credits are not a license to spend. Unknown free eligibility remains visible/unverified and is not automatically probed.
- Working requires usable generated text from a real inference call through the exact API route advertised to consumers. Model listing and CLI success are not direct-API proof.
- Identity is provider + credential reference + model + API route. Never merge two providers solely because their model IDs match. Multiple route seeds for one key are not multiple credentials.
- Every stored credential is accounted for. Disabled/retired entries are shown explicitly, not silently reactivated. Missing owner is Unassigned, never a fabricated email. Missing/CLI-only credentials remain visible with explicit unsupported/signin status, not falsely API-working.
- Every eligible active key/model pair is queued. Daily plus manual sweeps, with per-provider/key pacing and cooldowns, no silent model limit. Pending/blocked coverage is visible.
- SQLite persists current observations, check history, feedback, cooldowns and selection history. Secrets remain in the existing secret store/runtime seed, not the status database.
- A failure applies to the exact connection unless the evidence establishes a credential-wide problem. Feedback immediately makes the reported connection suspect/ineligible and schedules verification. Confirmed revoked/invalid credentials affect the key; rate limits preserve retry information.
- A success expires to Stale after 30 hours. Stale is not Failed. A later failure supersedes a previous success. Future/invalid timestamps are not fresh evidence.
- A key is Working iff at least one eligible connection is Working. An owner is Working iff at least one owned key is Working. Failed/unknown siblings do not negate success. Coverage is separate from health.
- Models sort by availability first, then Artificial Analysis Coding Index descending, with unscored last within the availability group. Never substitute the Intelligence Index. AA aliases must be explicit and conservative; no invented matches/scores. Working unscored models precede unavailable scored models. Show AA freshness/provenance; cache AA daily rather than on every UI refresh.
- Model catalog keeps every discovered free model visible regardless of availability, and uncertain entries clearly distinguished. UI may paginate/filter but cannot silently cap provider inventory.
- Private, authenticated dashboard and authenticated machine API. User only; authorized clients act with their Keeper credentials. No public emails/keys.
- Get token returns an ACTUAL provider key, matching base URL, exact model ID, protocol and necessary connection headers/config. It is not a Keeper gateway token. Clients call the upstream directly.
- Select the freshest successful eligible candidate. If its last success is older than five minutes, verify first. Explore stale/unverified eligible alternatives when needed with bounded attempts/time, returning pending/no working connection honestly rather than a bad key. Do not select a connection currently cooling down or excluded by feedback. Never silently substitute another model.
- Returned connection identity lets a client report failure precisely. The UI and API expose Report failure/Get another for every model. Exclude the reported connection for replacement selection; verify an alternative for the same provider/model identity. No recursive/unbounded retries. If none works, say so.
- Do not put secrets in initial HTML, URLs, logs, normal catalog/status responses, SQLite records or test artifacts. Dedicated authenticated credential responses must be non-cacheable. Secret retrieval and browser mutations require safe session/CSRF handling; do not expose the Keeper bearer to page source or persistent browser storage.
- UI: dark, compact readable dashboard with Accounts and Models tabs, expandable details, search/provider filter, labelled states and timestamps, progress and manual checks. Follow UI UX Pro Max data-dense dashboard guidance; contrast, keyboard focus, semantic buttons and reduced motion. No framework required; preserve stdlib server unless necessary.
- Scope: Keeper UI + API + examples first, not pi/OpenCode consumer integration and not a new inference proxy. Existing gateway behavior is not the deliverable.
- Delivery: implement, test, deploy live keeper.pkubelka.cz and verify without exposing credentials. Do not claim all checks succeeded; prove complete accounting and real observed outcomes, including provider failures and delayed jobs.

## UI mockups (illustrative only)

```text
KEEPER                                    [Check all]
[ Accounts ] [ Models ]                   Sweep: 42 / 60 checked

ACCOUNTS
Email              Status     Working keys    Coverage
alice@example.com  WORKING    1 / 2           8 / 8 checked
bob@example.com    WORKING    1 / 1           4 / 4 checked
carol@example.com  CHECKING   0 confirmed     1 / 4 checked

▾ alice@example.com
  ▾ Provider X · key …1234    WORKING: 2 / 4 models
    Model A   Working         checked 2m ago
    Model B   Working         checked 2m ago
    Model C   Rate-limited    retry at 14:30
    Model D   Access denied   checked 2m ago

MODELS                      [Search] [Provider: All]
Availability first → AA Coding Index descending
Model / Provider    Status        AA coding   Keys   Action
Model A / X         Working       58          4      [Get token]
Model B / Y         Working       49          2      [Get token]
Model C / X         Working       —           1      [Get token]
Model D / Z         Rate-limited  62          0      [Details]
Model E / Y         Not checked   —           —      [Check]

▾ Selected model
  [Get verified token] [Copy connection config]
  Provider · Model ID · Endpoint · Verification time
  [Report failure / Get another token]
```

## Architecture and important migration boundaries

Use a small availability domain module and SQLite store as the source of truth for new catalog/selection/UI behavior; do not add more special-case HTML over the current keyqueue ledger. Separate discovery (pricing/access metadata), inference observations, aggregation, selection and rendering. Reuse correct protocol adapters, keeping network/time injectable in tests. Background scheduler and manual/on-demand verification must not block ordinary page reads or race stale results over newer feedback. SQLite transactions/locking and persisted jobs must make restart recovery honest.

Existing server.py/matrix.py/aa.py/inventory.py and probe/keyround.py currently mix incompatible evidence. Historical aggregate state, baked keyqueue values and CLI pass must not be imported as direct per-model success without exact trusted evidence. Existing probe ingest must not fan out unscoped success to every key. Status/legacy surfaces should not contradict the new authoritative view.

Current production PROBE_DB is allocation-local, so replacement allocs lose it. Deployment must provide durable SQLite storage for the new store, with a bounded backup/migration plan before changes. Avoid wiping existing data. Persist errors explicitly rather than pretending a failed database write succeeded.

## Acceptance

1. Two providers with identical model IDs remain separate; a successful model B never creates model A success.
2. Full eligible Cartesian coverage for each provider's keys and free catalog; failed/unknown/stale/disabled entries remain accountable; no first-success early exit in sweeps.
3. Any-success key/email aggregation, correct counts, honest unknown/stale/cooldown status, ownership without synthetic fallback.
4. SQLite recovery across process restart and production allocation replacement; current observations, history, feedback and cooldowns agree.
5. Catalog ranking uses availability then Coding Index only; AA outages preserve last-known scores with stale evidence.
6. Token selection verifies old evidence and returns the matching upstream connection only; precise feedback excludes failures and replacement stays on the requested model; no candidates is explicit.
7. Authentication, CSRF/session mutation safety, no-store credential responses and secret-redaction tests.
8. Dark responsive Accounts/Models UI, functional copy/report/check controls and visible complete coverage.
9. Hermetic Python tests plus fake-provider end-to-end coverage across multiple keys/models/providers. No live inference in unit tests.
10. Live deployed build identity, authenticated catalog/account proof, full sweep accounting, at least one real verified token used against its exact provider/model without logging the token, and persistence proof. Quota/unavailable providers are reported honestly, not fabricated passing results.

## Baseline

Source base fd66590. Isolated worktree wt/keeper-all-models, branch feat/keeper-all-models.
Baseline: `(cd keeper && python3 -m pytest -q)` 149 passed; probe 46 passed; scripts 11 passed. Running scripts tests from root fails on their pre-existing relative import; run them from scripts/.
Graft lookup attempted; repository has no graph and fallback workspace has no build_matrix symbol. Use scoped source searches for this unindexed repository.
