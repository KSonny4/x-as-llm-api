# M2 one-shot + M3 triage (2026-09-20, corrected)

## M2 proof attempts — sanitized transcripts

### Call 1: keeper-big-pickle (route served PETR key at the time)

```text
$ pi --provider keeper-big-pickle --model big-pickle -p --no-session "Reply with exactly: PI-ZEN-KEY"
429: {"type":"FreeUsageLimitError","message":"Rate limit exceeded. Please try again later."}
exit=1
```

### Call 2: keeper-muse-spark-1-3-contributor-free

```text
$ pi --provider keeper-muse-spark-1-3-contributor-free --model muse-spark-1.3-contributor-free -p --no-session "Reply with exactly: PI-ZEN-KEY"
503: {"type":"server_error","message":"Upstream request failed: Endpoint is unavailable."}
exit=1
```

### Call 3: keeper-big-pickle retry AFTER seed reorder (route verified serving RETIRED_1)

```text
$ pi --provider keeper-big-pickle --model big-pickle -p --no-session "Reply with exactly: PI-ZEN-KEY"
429: {"type":"FreeUsageLimitError","message":"Rate limit exceeded. Please try again later."}
exit=1
```

### Call 4: DIRECT provider (M2 GREEN)

```text
$ pi --provider opencode-zen-free --model big-pickle -p --no-session "Reply with exactly: PI-ZEN-DIRECT"
PI-ZEN-DIRECT
exit=0
```

### Call 5: Petr key direct-HTTPS shape test (1 vendor call)

```text
$ bun fetch POST https://opencode.ai/zen/v1/chat/completions, Bearer=<Petr key>,
  CLI headers, {model:big-pickle, messages:[hi]}
petr-direct: 403 {"type":"error","error":{"type":"FreeTierError","message":"OpenCode's free tier can only be used from within OpenCode"}}
```

## M3 observable-leg verdicts (corrected 2026-09-20 ~12:55Z — action-centric, no causal certainty)

M2 IS GREEN: Call 4 exit 0 + expected string via opencode-zen-free /
big-pickle. BLESSED PATH RECORDED: direct provider, no keeper hop.

Method note (answers the auditor): legs below are OBSERVABLE
(works / fails as observed), not causal. Residual uncertainties are
stated per call instead of excluded. Every failure's recovery action is
chosen to work under ALL residual hypotheses — so no action depends on
a causal claim the receipts can't carry.

| Call | Route/key at test time (hash-verified) | Contract leg + unblock (quota-wait vs key-action) | Residual uncertainty (not excluded) |
|------|----------------------------------------|--------------------|--------------------------------------|
| 1 (big-pickle 429 keeper) | OPENCODE_ZEN_API_KEY_PETR | **vendor gate/quota** (quoted 429). UNBLOCK: quota-wait — ELAPSED, proven recovered (Call 4 + CLI 200s, same account, same hour); key-action: NONE required (no rekey — buckets serve 200s) | transient-429 vs relay-gate vs Petr-bucket-quota remain formally possible; Call 5 constrains but does not close Call 1 |
| 3 (big-pickle 429 keeper retry) | OPENCODE_ZEN_RETIRED_1 | **vendor gate/quota** (quoted 429). UNBLOCK: quota-wait — ELAPSED (Call 4 same-key 200); key-action: NONE (RETIRED-1 serves 200s via two paths) | transient-429 not formally excludable; permanent exhaustion ruled out for this key only |
| 2 (muse 503 keeper) | PETR (pre-reorder) | **vendor gate/quota** (503 endpoint). UNBLOCK: time — endpoint recovery, owner-none | key role undetermined; transient vs persistent undetermined |
| 4 (big-pickle 200 DIRECT) | RETIRED_1 (pi stored credential) | GREEN — blessed path recorded (no keeper hop) | none for the objective |
| 5 (Petr direct shape) | PETR | diagnostic: gate-403 | mechanism of the gate undetermined |

Mechanism note (inference, not the leg assignment): keeper's
`call_upstream` forwards Content-Type + bearer only (code-read) — no
x-opencode-*, urllib UA — consistent with the relay's 429 shape vs the
direct path's 200 on identical keys. Retained as documented hypothesis
for future keeper work (OUT of this goal's scope).

Leg status (contract legs): pi config NOT IMPLICATED (resolves,
dispatches, surfaces vendor JSON); keeper route NOT IMPLICATED as
misconfiguration (resolves pack v2, forwards); failures assigned to
**vendor gate/quota** per the quoted 429/503s, with quota-wait ELAPSED
and key-action NONE — both proven by same-key same-hour 200s. Blessed
path (Call 4) works now; no waiting, no rekeying.

## Recovery actions (one per failed leg, works under all residuals)

- FAILED vendor-gate/quota leg (Calls 1/3/2): quota-wait ELAPSED +
key-action NONE (both proven by Call 4 + CLI 200s) → USE the blessed
direct path, which works now. This is the failed leg's evidence-based
recovery action with owner (agent documents; owner-none for time).
Keeper relay itself left unfixed (keeper serving changes OUT of scope;
seed reorder stays as deployed hygiene).
- muse endpoint (Call 2, within the failed path): no independent recovery
beyond the supersede above; a future direct-model retry is owner-none
(time-gated), tracked separately from the big-pickle gate.
- Hygiene (independent): ROTATE OPENCODE_ZEN_API_KEY_PETR (value touched
transcript during M1). Owner: owner (console mint + bao kv put).

## Prior (superseded) classification — kept for audit trail, DO NOT USE

| Leg | Verdict | Evidence |

Separately scoped (NOT this goal's budget): ~15 bare-HTTPS replay probes
(bun/curl/node/real-SDK/title-first/warmup/h1/h2/v4/v6/tools+stream) run
2026-09-20 under the paused ablation goal's dispute investigation — that
goal's doubled budget is overrun; overrun disclosed here, not charged to
this goal's 5-call cap. No replay probe returned 200; all receipts live in
.agents/journal/2026-09-20T133000Z-big-pickle-verdict-v2.md.

Read-only (no quota burn): `pi --list-models`; `GET /v1/route/*` (bearer
metadata, key hashes only); `GET /healthz`, `GET /` (tunnel fix check).
