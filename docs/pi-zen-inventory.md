# Pi zen inventory (2026-09-20, keeper on new VPS)

## Actual `pi --list-models` output (zen-relevant rows)

```text
keeper-big-pickle                       big-pickle                       128K  16.4K  no  no
keeper-muse-spark-1-3-contributor-free  muse-spark-1.3-contributor-free  128K  16.4K  no  no
```

## Backing keys (names only, via GET /v1/route/:model)

BOTH providers route opencode-zen @ `https://opencode.ai/zen/v1`
(api=openai, features=chat/stream/tools, keeperPackVersion=v2),
backed by the single Bao key name `OPENCODE_ZEN_API_KEY_PETR`.

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
