# Availability foundation (Tasks 1–2)

This is a library foundation, **not yet wired into HTTP/UI or production**. It
must replace legacy aggregate/CLI evidence when Tasks 3–5 connect it. Nothing
imports `probe-seed.json`, `keyqueue.json`, legacy probe SQLite or CLI success.

## Modules and use

```python
from store import Store
from availability import Availability
from credentials import RuntimeCredentials
from discovery import CatalogDiscovery
from sweeps import Sweeps

store = Store('/var/lib/keeper/availability.db')
service = Availability(store)                 # optional clock=callable
service.sync_seeds(routes)                     # trusted runtime seed list
runtime = RuntimeCredentials(routes)           # secrets stay in this object
catalogs = CatalogDiscovery(service)           # optional transport=callable
worker = Sweeps(service)                       # durable pacing/leases

catalogs.refresh(routes)                       # background/admin task, not GET
sweep_id = worker.schedule('manual')           # all currently eligible pairs
worker.run_once(runtime.resolve)               # performs at most one real call
progress = worker.progress(sweep_id)
accounts = service.accounts()                  # local, secret-free snapshots
catalog = service.catalog()
connections = service.connections()
```

`worker.run(stop_event, runtime.resolve, lambda: catalogs.refresh(routes))` is
the blocking background loop for one supervisor-owned thread. It refreshes
catalogs before a daily sweep, persists daily dedup, and wakes interruptibly.
`run_once`/`claim`/`complete` support deterministic tests and bounded on-demand
selection. There is no thread startup or network work at import time.

- `schedule(kind='manual', credential_id=None, model_id=None)` accepts exact
  stored IDs. Manual sweeps share active jobs; they never clear cooldowns.
- `claim(connection_id=None)` returns a secret-free job/connection dict or None.
  None means blocked/paced/no due job, **not** a failed model.
- Resolve that job's `(provider, reference)` through `runtime.resolve`, then
  `inference.verify(job, secret, transport=..., clock=...)` and
  `worker.complete(job, result)`. Never pass a secret into SQLite.
- `service.report_failure(connection_id, reason)` fences in-flight checks,
  persists a reason from a bounded vocabulary, excludes that exact connection,
  and queues revalidation. Arbitrary client reason text is discarded.
- `service.history(connection_id)` and `feedback(connection_id)` expose safe
  history. `record_selection(connection_id)` records selection history; actual
  fresh-candidate selection and authenticated credential endpoints are Task 3.
- `begin_check` / `finish_check` are **low-level observation primitives**, not
  request-handler shortcuts: network callers must use `Sweeps` to honor pacing,
  leases, retry bounds and concurrent-worker exclusion.
- `inference.connection_config(connection, secret)` is deliberately SECRET-
  BEARING and contains exactly the tested base URL, endpoint, model, protocol,
  auth headers and API key. Task 3 must expose it only after selection, through
  an authenticated no-store response. Do not log it or put it in ordinary JSON.

Connection identity hashes non-secret `(provider, credential reference,
model, base URL, protocol)` components. A provider/model name alone is not a
connection ID. Catalog model IDs also retain API route/protocol distinctions.
A key with several seed model routes is one credential, not several keys.

Snapshots include `state`, `observation_state`, `blocked_reason`, `checked_at`,
`retry_at`, exact IDs, owner, pricing provenance and catalog freshness. No owner
becomes NULL/Unassigned. Disabled entries stay visible. All-sibling failure
never negates another eligible Working connection. Success becomes Stale at
30h; future observation times are Unknown. Pricing expires at 24h, independently
of health: old pricing cannot authorize new inference. `blocked_reason` must
always be checked in addition to any displayed state when selecting.

Sweep `total` counts eligible queued pairs, not all catalog pairs. `done` means
terminal attempts, including failed checks or exhausted abandoned leases—not
Working. Catalog/accounts `blocked` and `checked` are separate accounting.
There is no inventory cap or first-success exit. History records whether each
result applied. Later feedback/checks/eligibility changes fence old results.

## Runtime seeds and rotation

`provider`, `env_var` or `credential_ref`, `model`, `base_url`, `wire`, `owner`,
`active`, `bao_status`, `api_key` follow existing seeds. Unsupported or missing
API credentials stay visible but are not probed. Missing pricing stays blocked.

**Production MUST use a generation-specific `credential_ref`.** The renderer
now emits `<Bao key name>@bao:<KV metadata.version>`. Rotation of an in-place Bao
key creates independent Unknown/non-revoked evidence; old generation rows stay
disabled for history. RuntimeCredentials resolves the same versioned reference.
Do not reuse a reference for a different secret. Version bumps on metadata-only
writes conservatively reverify, rather than carrying proof to a new generation.
Bao `status`, never a `RETIRED` substring in the name, controls active status.
The renderer no longer invents fallback owner emails, passes secrets through
stdin rather than process arguments, retains account_id/tier metadata, and
emits real Kilo credentials with its documented API route. Seed JSON itself
remains secret-bearing and must be handled with restrictive permissions.

Providers without machine pricing can use explicit trusted per-model metadata:

```json
{
  "free_eligibility": {
    "kind": "zero_price",
    "provenance": "https://provider.example/pricing",
    "verified_at": 1800000000
  }
}
```

`recurring_allowance` is also accepted. It independently requires credential
`free_tier: true`, `no_paid_fallback: true` and `tier_provenance`. These assertions
must be verified by the operator; credits/trials do not qualify. In Bao the
renderer takes exact model metadata from `model_eligibility[model_id]` and tier
fields from the credential record. Refreshing seeds does not renew old pricing
timestamps. The current Gemini credential has no tier/billing proof and must
remain `free_tier_unverified` even for a documented free-tier model.

## Discovery and primary-source evidence

Fetched public metadata on 2026-09-20 without credentials or inference:

- OpenRouter: <https://openrouter.ai/api/v1/models>, 446 models, 24 zero-price
  entries under the conservative all-price-fields-zero rule. Requires both
  `pricing.prompt` and `pricing.completion`; missing/negative/nonfinite pricing
  never means free. Other nonzero charges also disqualify a model.
- Kilo: <https://kilo.ai/docs/gateway/api-reference> and
  <https://kilo.ai/docs/gateway/models-and-providers>. Base URL
  `https://api.kilo.ai/api/gateway`, bearer `/chat/completions`, priced `/models`.
  Public catalog observation: 380 models, 23 zero-price. 402/403 are connection
  denial, not global key revocation.
- Zen official source:
  <https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/zen.mdx>
  (published docs <https://opencode.ai/docs/zen/>). Join exact endpoint-table
  display names to pricing-table names; never infer free from suffixes or the
  ID-only <https://opencode.ai/zen/v1/models> catalog. Observed 73 documented
  endpoints, 7 documented free models. Six use supported text protocols; Jev
  uses non-text `/systemone` and remains Unsupported. Spark contributor free
  uses `/responses`, not `/chat/completions`. Document/list drift fails closed.
- Gemini: <https://ai.google.dev/gemini-api/docs/pricing>. Observed 18 exact
  standard free-tier model IDs in public pricing tables. Join against paginated
  authenticated `v1beta/models` and `generateContent` capability. Never assume
  every Gemini model is free or every credential is a free-tier credential.

Discovery queries every active supported credential, not just the first key.
OpenAI cursor/token and Gemini token pagination are supported. Per-key results
are unioned by exact model route; conflicting prices fail closed. Failed
refreshes preserve prior entries with their original freshness and a sanitized
per-key error. Seed-only and unsupported entries remain visible. No provider
response/error body is persisted. Public parser format changes block instead
of guessing. Live catalog counts are observations, not hardcoded expectations.

Cloudflare seeds now retain the real account_id and credential, but there is no
approved text adapter or account no-paid-fallback proof here. Other unsupported
CLI/OAuth providers likewise remain visible/blocked; no placeholder prose is
used as evidence that an account lacks credentials. Their inventories are not
claimed checked. Unknown providers with OpenAI listing support can discover
IDs, but only explicit verified pricing permits inference.

## Store, recovery and operational boundary

SQLite uses WAL, foreign keys, a versioned namespaced schema, transactions and
cross-thread/process claim locking. Existing unrelated tables remain untouched.
Checks, feedback, selections, discovery state, jobs, cooldowns, pacing and sweep
membership persist. Unexpired leases cannot be stolen at restart. Expired
leases are fenced/requeued within the attempt bound. Rate-limit retry headers
(seconds or HTTP dates) are retained as cooldowns; manual checks cannot bypass
them. Malformed/transient/403 errors do not revoke a credential. Confirmed
machine-coded invalid credentials do. DB errors propagate; they are not reported
as successful writes. Request bodies/text and raw provider errors never enter DB.

Task 5/parent must package these new modules, initialize the service once, and
mount durable storage. Parent reconnaissance: active Nomad API is
`http://127.0.0.1:4647`; old `https://nomad.pkubelka.cz` is not the usable API.
Docker volumes are enabled on `ovh-nomad-fresh`; only registry-data currently
exists as a host volume. Proposed parent-provisioned bind:
`/opt/nomad-volumes/keeper:/var/lib/keeper`. Current PROBE_DB is allocation-local.
Parent owns backup, directory ownership/permissions, migration, mount validation,
rollout and persistence proof. No foundation deployment occurred.

## Remaining Tasks 3–5

Implement five-minute revalidation/freshest selection and bounded same-model
replacement using this paced interface. Add authentication/session/CSRF/no-store
protections, then wire UI and stop legacy aggregate/CLI paths from advertising
contradictory verification. AA ranking must use Coding Index only (official
<https://artificialanalysis.ai/api-reference>,
`evaluations.artificial_analysis_coding_index`, daily cache, attribution link).
Do not treat this foundation's local test success as production proof.
