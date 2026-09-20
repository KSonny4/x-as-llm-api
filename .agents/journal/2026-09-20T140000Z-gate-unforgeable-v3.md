# 2026-09-20T~14:00Z — verdict v3: gate unforgeable from outside the binary

## What was built (per owner: minimalist CLI, Go, no Python, no binary dep)
`zencli/` in-repo: Go + uTLS, BoringSSL-mimic ClientHello, hand-framed
HTTP/1.1 with exact CLI header order, title→main same-connection,
key via env only. Builds to a single 8MB binary.

## The capture breakthrough (localhost intercept, key scrubbed from disk)
- CLI handshake: 17 ciphers no-GREASE, 14 extensions fixed order, ALPN
  http/1.1, groups X25519/secp256r1/secp384r1, sigalgs Chrome+SHA1-RSA,
  no compress-cert/ALPS/ECH. (`/tmp/zcap`, scrubbed; NOT in git.)
- CLI request anatomy: title call = POST /zen/v1/responses (Responses API
  shape, 2.6KB) → 401 CreditsError; main = POST /zen/v1/chat/completions
  (91.6KB: 41KB system + 31 tools + tool_choice + stream) → 200.
- Catalog fetch = unauthed GET models.opencode.ai/api.json (public).
- zencli's hello verified byte-equivalent via capture before the live test.

## Decisive result
zencli with byte-identical handshake + byte-identical bodies + identical
headers + same-connection sequencing: title 401 (matches CLI), main **403**.
Same key (hash-verified), same host, same machine.

## Eliminated in total (this turn + prior ablation)
Key, endpoint, host, model string, header names/values/order/casing, body
(byte-identical 94KB replay), TLS handshake (byte-identical profile),
HTTP version, ALPN, IP family, session id format/freshness/real-session,
call sequence, connection reuse, catalog warmup, config override, SDK
stack (real ai-sdk request also 403s), TCP SYN fingerprint (same kernel).

## Verdict
No reconstructible request passes. The discriminator is outside every
observable/practicable wire layer (unobservable TCP behavior or
server-side login-bound state). Building a passing minimalist CLI by
mimicry is NOT possible with current evidence — proven, not asserted.
Honest residual: a sub-TCP signal (untestable without kernel
instrumentation) or a future gate change (zencli is kept ready).

## Working path (unchanged)
Binary-on-Nomad: pi-zen-bridge CLI-subprocess at >=1024MB (69 passes
proven). keeper HTTP relay for zen: retired by vendor design.
