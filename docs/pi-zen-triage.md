# M2 one-shot + M3 triage (2026-09-20)

## M2 proof attempts — sanitized transcripts

### Call 1: keeper-big-pickle

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

## M3 leg classification (evidence-backed)

| Leg | Verdict | Evidence |
|-----|---------|----------|
| pi config | GREEN | providers resolve via --list-models; request dispatched; vendor JSON error surfaces (chain works end to end) |
| keeper route | GREEN | /v1/route resolves pack v2 with bearer auth; request forwarded upstream |
| vendor gate/quota | BLOCKED (both) | big-pickle: `FreeUsageLimitError` 429 (quota bucket empty); muse: `Endpoint is unavailable` 503 (vendor capacity) |

Both failures are vendor-side. No re-probing until buckets refill /
endpoint recovers. Blessed path (pending recovery): keeper-big-pickle
→ big-pickle, single confirming call when 429s are known-clear elsewhere.

## Unblock ownership

- Quota/capacity: WAIT (vendor window; no owner action exists) — owner: none.
- Credential hygiene: ROTATE `OPENCODE_ZEN_API_KEY_PETR` (value touched
  transcript 2026-09-20 during M1) — owner: mint at vendor console +
  `bao kv put`, then agent re-seeds keeper + refreshes pi providers.

## Auditable total-call ledger (≤5 test calls)

Vendor-touching test calls (chat completions): **2**
1. pi one-shot via keeper-big-pickle → 429 (above)
2. pi one-shot via keeper-muse-spark-1-3-contributor-free → 503 (above)

Non-billable read-only calls (no quota burn, listed for auditability):
- `pi --list-models` (local config read)
- `GET /v1/route/big-pickle`, `GET /v1/route/muse-spark-1.3-contributor-free`
  (bearer, route metadata)
- `GET /healthz`, `GET /` (keeper reachability after tunnel fix)

Remaining budget: 3 calls, held for the single confirming retry.
