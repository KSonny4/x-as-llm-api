# E2E: all keys × free models — what worked (2026-09-19)

Sweep: dispatch `f5682076`, 89/89 reported. 103 routes seeded (33 keys +
70 zen free-model routes: 7 models × 10 keys). Source: live matrix.

## Works fully (ok, direct HTTP)

- OpenRouter `gpt-4o-mini` × 4 keys — the only direct-HTTP oks.

## Works via opencode CLI (degraded: direct chat tier-denied, CLI passes)

All 10 keys, identical across keys (CLI uses its own login):

- big-pickle, ling-3.0-flash-fin-free, mimo-v2.5-free,
  muse-spark-1.2/1.3-contributor-free, nemotron-3-ultra-free:
  10/10 degraded (CLI serves them)
- nemotron-3.5-lightning-free: 9 degraded + 1 transient L2-down

## Dead (down on all keys, CLI also fails)

- jev-1.13-free: 10/10 down (L1 suspect + L2 fail) — model gone/renamed
  upstream, not a key problem.
- gemini-3.6-flash, claude-sonnet-4-6 (×3 conns): down (pre-existing,
  non-zen, unchanged by this sweep).

## Throttled, honestly (limited)

- kimi-k2.7-code: 429 backoff (never deny — retries later).

## Reading

Free-tier Zen keys: `/models` 200, direct chat 403 (FreeTierError),
CLI green — for every key × every live free model. `degraded` IS the
working state for CLI-driven use. jev-1.13-free is the only free model
nothing can serve.
