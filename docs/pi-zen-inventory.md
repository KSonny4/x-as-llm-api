# Pi zen inventory (2026-09-20, keeper on new VPS)

## Actual `pi --list-models` output (zen-relevant rows)

Keeper-relayed rows:
```text
keeper-big-pickle                       big-pickle                       128K  16.4K  no  no
keeper-muse-spark-1-3-contributor-free  muse-spark-1.3-contributor-free  128K  16.4K  no  no
```

Direct rows (pi-opencode-direct@0.1.6, pure-HTTP CLI-identity provider):
```text
opencode-zen-free  big-pickle                     200K    32K     yes  no
opencode-zen-free  ling-3.0-flash-fin-free        262.1K  32.8K   yes  no
opencode-zen-free  mimo-v2.5-free                 200K    32K     yes  yes
opencode-zen-free  muse-spark-1.2-contributor-free 1.0M   131.1K   yes  yes
opencode-zen-free  muse-spark-1.3-contributor-free 1.0M   131.1K   yes  yes
opencode-zen-free  nemotron-3-ultra-free           1M     128K     yes  no
opencode-zen-free  nemotron-3.5-lightning-free     262.1K 262.1K   yes  no
```
Backing (names only): pi stored credential for opencode-zen-free
(~/.pi/agent/auth.json `key`, len 67) hash-matches Bao
OPENCODE_ZEN_RETIRED_1 — same working key as the CLI. Resolution order
per extension docs: stored credential → env OPENCODE_API_KEY →
anonymous. Provider stamps CLI-identity headers (UA opencode/1.18.31…
pi-opencode-direct/0.1.6, x-opencode-client: cli,
x-opencode-project: global).

Excluded from this goal: `meta`/`omniroute` muse rows (unrelated
providers that happen to name-match the grep — different vendors/
credentials, not zen); paid models (CreditsError, no billing attached).

## Backing keys (names only, via GET /v1/route/:model)

HISTORICAL (M2 Calls 1-2 ran against this): BOTH providers routed
opencode-zen @ `https://opencode.ai/zen/v1` backed by the single Bao key
name `OPENCODE_ZEN_API_KEY_PETR`.

CURRENT (post seed-reorder, deployed + hash-verified 2026-09-20): BOTH
providers resolve RETIRED_1-backed routes first
(`zen/retired-1`, api=openai, features=chat/stream/tools,
keeperPackVersion=v2). M2 Call 3 ran against this config and still 429d
(see triage) — key verified identical to the CLI's working key.

## Notes

- `/v1/route/:model` returns LIVE key material to any bearer holder
  (by design — pi needs it). Treat KEEPER_TOKEN as key-equivalent.
- 2026-09-20: the Petr key value touched the agent transcript during
  inventory (route output) → ROTATION REQUIRED after proof done
  (owner: mint at vendor console,
  `bao kv put secret/projects/pi-infinity-llm/OPENCODE_ZEN_API_KEY_PETR`,
  then keeper re-seed + pi provider refresh).
- Tunnel incident same day: keeper ingress rule vanished from the
  `nomad-148-113-245-89` Cloudflare tunnel config (public 404s);
  re-added via API, public 200 again. Remover unknown.
