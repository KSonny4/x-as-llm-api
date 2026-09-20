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

## M3 classification (receipt-backed, per call)

| Call | Route key at test time (hash-verified) | Verdict | Evidence |
|------|----------------------------------------|---------|----------|
| 1 (big-pickle 429) | OPENCODE_ZEN_API_KEY_PETR | drained-key misroute (agent config error, fixed) | local CLI on RETIRED_1 returned live 200 same hour; route served PETR hash at test time |
| 3 (big-pickle 429 retry) | OPENCODE_ZEN_RETIRED_1 | relay-path gate: same key 200s via CLI binary, 429s via keeper HTTP relay | route hash re-verified RETIRED_1 post-reorder before retry; CLI ALIVE-CHECK-77 200 same hour |
| 2 (muse 503) | PETR (pre-reorder) | vendor capacity (endpoint down, not key-specific) | `Endpoint is unavailable` — model-endpoint shape, no key bucket implicated |

Leg status: pi config GREEN (resolves, dispatches, surfaces vendor JSON);
keeper route GREEN (resolves pack v2, forwards); vendor gate BLOCKS the
HTTP-relay path per Call 3's same-key split (CLI 200 vs relay 429).

## Single unblock per failure (owner + responsible party)

- Call 1 cause: FIXED by agent (seed reorder RETIRED_1-first, redeployed,
  route verified serving RETIRED_1 for both models 2026-09-20).
- Calls 3/2 residual: NO in-scope fix — the contracted chat-completions
  path (pi → keeper HTTP relay → zen) is vendor-gated per the Call 3
  receipt. Next: follow-up goal (binary-on-Nomad incl. Go client
  experiment). Responsible: owner approves follow-up scope; no quota wait
  (bucket proven non-empty) and no blind retries.
- Hygiene (independent): ROTATE OPENCODE_ZEN_API_KEY_PETR (value touched
  transcript during M1). Responsible: owner (vendor console mint +
  `bao kv put`); agent re-seeds after.

## Auditable total-call ledger

THIS goal's vendor-touching chat calls: **3 of 5** (Call 1 → 429,
Call 2 → 503, Call 3 → 429). No further chat calls after Call 3.

Separately scoped (NOT this goal's budget): ~15 bare-HTTPS replay probes
(bun/curl/node/real-SDK/title-first/warmup/h1/h2/v4/v6/tools+stream) run
2026-09-20 under the paused ablation goal's dispute investigation — that
goal's doubled budget is overrun; overrun disclosed here, not charged to
this goal's 5-call cap. No replay probe returned 200; all receipts live in
.agents/journal/2026-09-20T133000Z-big-pickle-verdict-v2.md.

Read-only (no quota burn): `pi --list-models`; `GET /v1/route/*` (bearer
metadata, key hashes only); `GET /healthz`, `GET /` (tunnel fix check).
