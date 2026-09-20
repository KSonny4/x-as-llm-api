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
  shape matches the relay path seen in Call 3 (429 on RETIRED_1, a key
  proven non-empty by Call 4 + CLI 200s); a Petr-bucket quota
  contribution cannot be excluded from this evidence alone — different
  paths can meet different checks. UNBLOCK (identical either way): use
  the blessed direct path. The seed reorder stays as deployed hygiene,
  NOT as a fix for a proven misroute.
- Call 3, big-pickle 429 retry, route=RETIRED_1: RECEIPT route-hash=
  RETIRED_1 + CLI ALIVE-CHECK-77 200 + Call 4 pi-direct 200, same key
  same hour → INFERENCE relay-path gate (key-bucket quota excluded for
  THIS key by the two 200s). NO in-scope fix in
  chat-completions-over-HTTP-relay (keeper serving changes OUT).
- Call 2, muse 503, route=Petr(pre-reorder): RECEIPT `Endpoint is
  unavailable` → INFERENCE vendor-side endpoint failure,
  endpoint-shaped; the response carries no key-specific signal, and the
  key's role is undetermined from this evidence alone (the earlier
  "key-independent" label is withdrawn as overconfident). UNBLOCK
  (owner: none): retry when the endpoint recovers. Independent of the
  big-pickle gate; tracked separately, not grouped.

Original (superseded) labels — kept for audit trail, DO NOT USE:
- Call 1 was labeled "drained-key misroute (agent config error). FIXED" —
  WITHDRAWN (see above).

## C. Exact vendor-call ledger (agent-driven, reconstructed 12:30Z)

THIS goal chat-completions calls (cap 5): FINAL 5 of 5 — Call 1 (429
keeper), Call 2 (503 keeper), Call 3 (429 keeper retry), Call 4 (200
DIRECT, objective satisfied), Call 5 (Petr direct-shape 403,
discriminating receipt). Cap reached exactly; no further vendor calls.

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

## E. Live identifier check (M1 correction)

Committed inventory provider id corrected to live
`keeper-muse-spark-1-3-contributor-free` (dashes; model id keeps dots:
`muse-spark-1.3-contributor-free`). Triage transcripts already used the
correct provider id and are unchanged.
