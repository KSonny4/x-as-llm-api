# Pi → zen request journey (blessed direct path, proven 200)

Prompt used: `pi --provider opencode-zen-free --model big-pickle -p --no-session "Reply with exactly: PI-ZEN-DIRECT"` → `PI-ZEN-DIRECT`, exit 0.

```text
┌──────┐  prompt   ┌──────────────────┐  HTTPS+Bun+CLI-id  ┌─────┐  ┌──────────┐
│ you  │ ────────▶ │ pi (Bun 1.3.14)  │ ─────────────────▶ │  CF │─▶│ zen      │
└──────┘           └──────────────────┘  POST /zen/v1/     └─────┘  │ backend  │
                           │              chat/completions         │ 200 + SSE│
                           │                                       └──────────┘
                   credential + headers attached here (never leaves TLS)
```

## Hop 0 — you → pi (local, no network)

- pi parses `--provider opencode-zen-free --model big-pickle`.
- Resolves the provider definition from `~/.pi/agent/models-store.json`:
  `baseUrl https://opencode.ai/zen/v1`, stamped headers
  (`User-Agent: opencode/1.18.31 … pi-opencode-direct/0.1.6`,
  `x-opencode-client: cli`, `x-opencode-project: global`).
- Loads the bearer from pi's stored credential
  (`~/.pi/agent/auth.json`, hash-verified = Bao `OPENCODE_ZEN_RETIRED_1`).
- Builds the chat body: `{model, messages, stream:true, …}` in pi's
  OpenAI-completions shape (this exact body shape is part of why the
  gate passes — hand-rolled minimal bodies 403).
- Retry policy resolves to **0 provider retries** (settings `retry: null`
  → `maxRetries ?? 0` in pi 0.85.1 source) → exactly 1 upstream attempt.

## Hop 1 — pi → Cloudflare → zen (the wire)

- **TLS**: Bun's BoringSSL handshake — captured profile: 17 ciphers,
  no GREASE, 14 extensions, ALPN `http/1.1` (verified byte-identical to
  the genuine CLI's hello via localhost capture).
- **HTTP**: `POST /zen/v1/chat/completions` with Authorization bearer +
  full CLI-identity headers + pi session-affinity headers
  (`x-client-request-id`, `session_id`).
- **Vendor sees**: a request indistinguishable in all identity signals
  from legitimate CLI traffic → gate passes → `200` + SSE stream.
- pi parses the stream, prints `PI-ZEN-DIRECT`, exit 0. Total: 1 vendor
  call, ~1 short completion of quota.

## Contrast: the keeper path (Calls 1–3 → 429)

```text
│ pi │ ──▶ CF tunnel ──▶ keeper (Nomad) ──▶ zen ❌ 429
            bearer KEEPER_TOKEN   │ strips identity here:
                                  │ urllib UA, Content-Type + bearer ONLY
                                  │ (code-read: keeper call_upstream)
```

Same keys, same vendor — but keeper forwards a *bare* request (no
`x-opencode-*`, Python-urllib UA). The vendor sees an unidentified
client and answers `429 FreeUsageLimitError` instead of `403` (bare
replays) or `200` (full identity). Path — not key, not quota — is the
variable (proven by Call 3 vs Call 4 on the identical key).

## Contrast: the genuine CLI (reference, 200)

1. `GET models.opencode.ai/api.json` — public catalog, **unauthed** (no
   key involved; cannot be the gate signal).
2. `POST /zen/v1/responses` title call (gpt-5.4-nano, 2.6KB) → 401
   CreditsError (paid model, no billing — fails silently, non-fatal).
3. `POST /zen/v1/chat/completions` main call (91.6KB: 41KB system +
   31 tools + stream) on the same keepalive connection → 200.

## Where secrets live per hop (names only)

| Hop | Secret | Stored in |
|-----|--------|-----------|
| pi → zen | zen key (RETIRED_1) | pi `auth.json` (local disk, 600) + Bao escrow |
| pi → keeper | KEEPER_TOKEN (v2) | Bao; deployed as task env on Nomad |
| keeper → zen | zen key (RETIRED_1 post-reorder) | keeper seed JSON (rendered Bao→deploy, never git) |
| anywhere in git | none | tripwire + full-history scans clean |
