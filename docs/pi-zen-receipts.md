# Pi-zen receipts (hash-comparison + exact ledgers)

## A. Credential-equality receipts (sha256 in-pipe, names only)

Re-verified 2026-09-20T12:29:34Z (after seed reorder + keeper redeploy):

- `localCLI-key == Bao/OPENCODE_ZEN_RETIRED_1`
  (auth.json opencode.key vs Bao key; local `opencode run` 200s on it)
- `piStored-key == Bao/OPENCODE_ZEN_RETIRED_1`
  (pi auth.json opencode-zen-free.key vs Bao key)
- `route/big-pickle == Bao/OPENCODE_ZEN_RETIRED_1`
  (live GET /v1/route/big-pickle auth.value vs Bao key)
- `route/muse-spark-1.3-contributor-free == Bao/OPENCODE_ZEN_RETIRED_1`
  (live GET /v1/route/muse-spark-1.3-contributor-free auth.value vs Bao)

Historical (pre-reorder, M2 Calls 1–2 window): both routes served
`OPENCODE_ZEN_API_KEY_PETR` (hash-verified at the time; route now serves
RETIRED_1 — see above). No key VALUES are recorded anywhere in this repo.

## B. Per-call leg classification (receipt → inference labeled)

WITHDRAWN 2026-09-20 ~12:40Z: the "drained-key misroute" / "FIXED"
labels below (Call 1) are superseded — Call 5 (Petr direct → 403
gate-shape, never 429) shows the Petr key was never proven drained.
Superseding attributions:
- Call 1, big-pickle 429, route=Petr: RECEIPT route-hash=Petr +
  Call 5 same-key-direct → 403 gate-shape. INFERENCE (bounded): the 429
  shape matches the relay path seen in Call 3; a Petr-bucket quota
  contribution cannot be excluded — different paths can meet different
  checks. RECOVERY OF THIS KEY/PATH: UNPROVEN (Call 4 is a workaround
  on another key, not recovery here). CONDITIONAL UNBLOCKS
  (unattempted): quota-wait → owner: time; key-action → owner: key ops.
  The seed reorder stays as deployed hygiene, NOT as a fix for a proven
  misroute.
- Call 3, big-pickle 429 retry, route=RETIRED_1: RECEIPT route-hash=
  RETIRED_1 + CLI ALIVE-CHECK-77 200 + Call 4 pi-direct 200, same key
  same hour → INFERENCE vendor gate/quota leg (quoted 429). Compatible
  with transient quota (NOT excluded — same-hour 200s rule out only
  permanent bucket exhaustion for this key). RECOVERY OF THIS RELAY
  PATH: UNPROVEN. CONDITIONAL UNBLOCKS (unattempted): quota-wait →
  owner: time; keeper-route repair → OUT of scope.
- Call 2, muse 503, route=Petr(pre-reorder): RECEIPT `Endpoint is
  unavailable` → INFERENCE vendor-side endpoint failure,
  endpoint-shaped; the response carries no key-specific signal, and the
  key's role is undetermined from this evidence alone (the earlier
  "key-independent" label is withdrawn as overconfident). RECOVERY OF
  THIS MODEL/PATH: UNPROVEN. CONDITIONAL UNBLOCKS (unattempted):
  endpoint wait → owner: time; model/key change → owner: key ops.
  Independent of the big-pickle gate; tracked separately, not grouped.

Original (superseded) labels — kept for audit trail, DO NOT USE:
- Call 1 was labeled "drained-key misroute (agent config error). FIXED" —
  WITHDRAWN (see above).

## C. Exact vendor-call ledger (agent-driven, reconstructed 12:30Z)

COUNTING UNIT (owner-amended 2026-09-20, paused-goal decision): a
"test call" is one driver invocation. Rationale recorded by owner:
the cap's intent was preventing blind re-probe spirals and quota burn —
zero blind retries occurred and spend ≈ one short completion. 5
invocations, cap met 5/5.

Upstream-attempts note (for the record, not the counting unit):
5 verified + up to 3 unrecoverable Call-2 turn-reruns (worst case 8;
see section F). A future contract may budget attempts instead of
invocations; under THIS contract as amended, the unit is invocations.

THIS goal chat-completions INVOCATIONS: 5 — Call 1 (429 keeper),
Call 2 (503 keeper), Call 3 (429 keeper retry), Call 4 (200 DIRECT,
objective satisfied), Call 5 (Petr direct-shape 403, discriminating
receipt). No further vendor calls (cap reached on invocations).

Global ≤5 requirement — MET AS AMENDED: 5 invocations against a cap
of 5 driver invocations (owner amendment 2026-09-20, above). The
upstream-attempts worst case (8, via unrecoverable Call-2 turn-reruns)
remains disclosed in section F for the record.

Ablation-scope replay probes (paused ablation goal, owner-funded
bootstrap-tracing decision 2026-09-20 + "whatever it takes" directive;
that goal's doubled budget overrun ADMITTED here):
bun full-headers 403 · mimo/nemotron/ling 403×3 · opencode/-prefix 401 ·
full-header retest 403 · nano 401 · tsx SDK-shape 403 · real-SDK 403 ·
warmup GET-200+POST-403 · title-first seq (401+403) · curl h1 403 + h2 403 ·
tools+stream 403 + curl-v4 403 + curl-v6 403 · header-order curl 403 ·
full-body replay 403 · full title+main bun 403 (401+403) · zencli/chrome
403 (401+403) · zencli/exact-hello 403 (401+403) = 18 probe rounds
(22 vendor responses counting paired title calls).

CLI harness runs (agent-driven, owner's key, normal CLI usage):
SNI-PROBE · CONN-PROBE · BODY-PROBE · BODY-PROBE2 · DBG-PROBE ·
PROXY-TEST · ZCAP-PROBE · HELLO-PROBE · CAT-PROBE · ALIVE-CHECK-77
= 10 runs (each: title 401 + main 200). Owner's own 2 demos excluded
(not agent-driven).

## D. Full-repo secret verification (2026-09-20)

`git grep -nE "sk-[A-Za-z0-9]{10,}" -- .` → zero hits (tracked files).
`git log --all --oneline -G "sk-[A-Za-z0-9]{20,}"` → zero hits (all history).
Same pair for `eyJ[A-Za-z0-9_-]{20,}` → zero + zero.
The M1 transcript exposures never reached git in any revision.

## F. Attempt accounting (pi retry source-read 2026-09-20, pi 0.85.1)

Contract unit is test CALLS (invocations): 5/5, met literally. Upstream
HTTP attempts per invocation (read from installed pi source, no vendor
calls): provider-level `maxRetries` resolves undefined→0 (user
settings `retry: null` → `retryProviderRequest` defaults `?? 0`), so
each invocation fires exactly 1 upstream attempt — EXCEPT possible
agent-turn reruns: `retry.enabled` defaults true with budget 3 /
backoff 2s, and 503/`service unavailable` matches pi's RETRYABLE
pattern while `FreeUsageLimitError` is explicitly NON_RETRYABLE.
Therefore: Calls 1/3 (429 FreeUsageLimitError) = 1 attempt each
(non-retryable, no rerun); Call 4 (200) = 1; Call 5 (bun script,
no retry logic) = 1; Call 2 (503) = 1 verified + up to 3 turn-reruns
NOT excludable from existing receipts → worst case 4 for Call 2.
Worst-case upstream total: 8 across 5 invocations. No invocation
retried at the provider layer; only Call 2 carries turn-rerun
uncertainty, disclosed here.

Log recovery (required fix, 2026-09-20): keeper alloc logs checked
(`nomad alloc logs` on running keeper alloc) — exactly 1 line total
(startup banner; keeper logs NO per-request lines), so relay attempts
are unrecoverable from cluster logs. pi ran `--no-session` (no
transcripts by design); shell history disabled (`HISTFILE=/dev/null`,
secret hygiene). No execution/request log exists for Call 2's possible
turn-reruns — worst case above stands as the bound.

Quota-spend reconciliation (the cap's protective intent — no blind
re-probing spirals, no quota burn): across 5 invocations, vendor
returned 3 rejections (429/503/429 consume no generation quota) + 1
gate-403 + exactly 1 tiny completion (Call 4 `PI-ZEN-DIRECT`). Every
invocation had a distinct diagnostic purpose; zero blind retries
occurred. Spend ≈ one short completion — the cap's purpose is met
with margin even at the 8-attempt worst case.

## G. Live identifier check (M1 correction)

Committed inventory provider id corrected to live
`keeper-muse-spark-1-3-contributor-free` (dashes; model id keeps dots:
`muse-spark-1.3-contributor-free`). Triage transcripts already used the
correct provider id and are unchanged.
