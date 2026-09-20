# zencli — minimalist zen chat client (Go, no Python, no opencode binary)

Raw-wire HTTPS client: BoringSSL-mimic ClientHello (uTLS) + hand-framed
HTTP/1.1 with the exact header order the genuine CLI emits. Key via
`ZEN_API_KEY` env only — never logged, never stored.

```bash
cd zencli && go build -o zencli .
ZEN_API_KEY=... ./zencli -pre title.json -body req.json
# -pre: optional first request on the same connection (title-then-main)
# -body: chat request JSON
# -addr host:port: dial override (observability harness)
```

## Result 2026-09-20: the gate is unforgeable from outside the binary

Byte-identical handshake (verified via CONNECT-proxy capture:
17 ciphers, 14 extensions, same groups/sigalgs, no GREASE/ECH) +
byte-identical bodies (94KB captured CLI request) + identical headers +
same-connection title→main still 403s while the binary 200s.
Every observable network layer eliminated — see journal
`2026-09-20T133000Z-big-pickle-verdict-v2.md` and v3 note.

Kept as: (a) proof instrument, (b) ready client if the gate ever
changes, (c) template for non-gated endpoints.
