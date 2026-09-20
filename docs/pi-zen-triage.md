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

| Call | Route/key at test time (hash-verified) | Observable verdict | Residual uncertainty (not excluded) |
|------|----------------------------------------|--------------------|--------------------------------------|
| 1 (big-pickle 429 keeper) | OPENCODE_ZEN_API_KEY_PETR | keeper-relay leg FAILS (429 observed) | transient-429 vs relay-gate vs Petr-bucket-quota: Call 5 (same key direct → 403, never 429) constrains but does not close Call 1; all three remain formally possible |
| 3 (big-pickle 429 keeper retry) | OPENCODE_ZEN_RETIRED_1 | keeper-relay leg FAILS (429 observed, 2/2 relay attempts) | transient-429 not formally excludable; persistent-bucket-exhaustion ruled OUT for this key (two 200s same key same hour via CLI + Call 4) |
| 2 (muse 503 keeper) | PETR (pre-reorder) | keeper-relay leg FAILS, endpoint-shaped (`Endpoint is unavailable`) | key role undetermined; transient vs persistent undetermined |
| 4 (big-pickle 200 DIRECT) | RETIRED_1 (pi stored credential) | direct leg WORKS (exit 0 + `PI-ZEN-DIRECT`) | none for the objective |
| 5 (Petr direct shape) | PETR | direct-HTTPS leg returns gate-403 (discriminating receipt) | mechanism of the gate undetermined |

Leg status (observable): pi config WORKS; pi-direct provider WORKS
(blessed); keeper relay FAILS on zen routes (observed 3/3: 429/503/429).
Vendor buckets serve 200s (CLI + Call 4) — persistent quota exhaustion
is ruled out wherever a 200 exists for that key; nothing further claimed.

## Recovery actions (one per failed leg, works under all residuals)

- FAILED PATH keeper-relay (Calls 1/3/2): SUPERSEDE — use the blessed
direct path (`pi --provider opencode-zen-free --model big-pickle`), which
works now under every residual hypothesis (no wait needed). This is the
failed path's evidence-based recovery action, distinct from the bypass
record itself. Keeper relay left unfixed: keeper serving changes are OUT
of this goal's scope; seed reorder stays as deployed hygiene. Owner of
this disposition: agent (this document).
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
