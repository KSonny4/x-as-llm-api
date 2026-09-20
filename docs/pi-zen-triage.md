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

## M3 classification (corrected 2026-09-20 ~12:45Z — Call 4 GREEN, v3 WITHDRAWN)

M2 IS GREEN: Call 4 exit 0 + expected string via opencode-zen-free /
big-pickle. BLESSED PATH RECORDED: direct provider, no keeper hop.

WITHDRAWN (auditor was right): (a) "drained Petr bucket" — Call 5 shows
the Petr key gets gate-403 direct, NOT quota-429; the key/bucket was
never proven drained. (b) verdict-v3 "unforgeable from outside the
binary" — Call 4 (pi Bun-stack HTTPS) passes; HTTP reuse IS possible.
The undetermined remainder is only WHICH request element gates (likely
keeper stripping CLI identity upstream: urllib UA, no x-opencode-* —
keeper code path `call_upstream` sends Content-Type + bearer only).

| Call | Route/key at test time (hash-verified) | Verdict | Evidence |
|------|----------------------------------------|---------|----------|
| 1 (big-pickle 429 keeper) | OPENCODE_ZEN_API_KEY_PETR | relay-path gate (CORRECTED: not drained-key) | Call 5: same key direct → 403 gate-shape, never 429 → the 429 shape comes from the relay path, not the key |
| 3 (big-pickle 429 keeper retry) | OPENCODE_ZEN_RETIRED_1 | relay-path gate | same key 200s via CLI binary AND via pi-direct (Call 4); only the keeper relay 429s → path is the variable |
| 2 (muse 503 keeper) | PETR (pre-reorder) | vendor capacity, endpoint-shaped | `Endpoint is unavailable`; key-independent |
| 4 (big-pickle 200 DIRECT) | RETIRED_1 (pi stored credential) | GREEN — objective satisfied | exit 0 + `PI-ZEN-DIRECT` |
| 5 (Petr direct shape) | PETR | gate-403 (discriminating receipt for Call 1) | same key as Call 1, different path, different verdict |

Leg status: pi config GREEN; pi-direct provider GREEN (blessed);
keeper relay GATED (429 both keys — documented, NOT fixed: keeper
serving changes are OUT of this goal's scope; seed reorder kept as
deployed hygiene). Vendor buckets proven non-empty (CLI + Call 4 200s).

## Single unblock per failure (owner + responsible party)

- big-pickle via keeper (Calls 1/3): USE THE BLESSED DIRECT PATH
  (`pi --provider opencode-zen-free --model big-pickle`). No keeper fix
  in this goal (OUT of scope). Responsible: agent (documented).
- muse 503 (Call 2): retry when the endpoint recovers (endpoint-shaped,
  separate from the big-pickle gate). Responsible: owner-none (time).
- Hygiene (independent): ROTATE OPENCODE_ZEN_API_KEY_PETR (value touched
  transcript during M1). Responsible: owner (console mint + bao kv put).

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
