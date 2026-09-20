# zencli — minimalist opencode-zen chat client

Single-file Go CLI (271 lines, `main.go` + `go.mod`/`go.sum`) that speaks
to `https://opencode.ai/zen/v1` with raw wire control no stock HTTP stack
offers. Builds to one static ~8MB binary. No Python, no Node, no opencode
binary, no runtime.

```bash
cd zencli && go build -o zencli .
ZEN_API_KEY=... ./zencli -pre title.json -body req.json
```

Flags: `-body` (chat request JSON, required), `-pre` (optional first
request sent on the same connection, e.g. the title call) + `-prepath`,
`-path` (default `/zen/v1/chat/completions`), `-host`, `-ua`,
`-session`/`-msgid` (generated `ses_`/`msg_` + 24 alphanumerics if empty),
`-addr` (dial override for observability harnesses).

## How minimal it is

- **One source file.** All logic in `main.go`: fingerprint spec (~90
  lines), request framing (~60), chunked/SSE response drain (~60), CLI
  (~60).
- **One real dependency**: `github.com/refraction-networking/utls`
  (uTLS) for ClientHello control. The rest (`x/crypto`, `x/net`,
  `x/sys`, brotli/compress) is uTLS's own transitive closure — nothing
  else. No HTTP framework, no JSON library beyond stdlib
  (`encoding/json` is only used implicitly — bodies pass through as
  opaque bytes; zencli never parses them).
- **No TLS config surface**: cert verification on, SNI from `-host`,
  ALPN forced to `http/1.1`.
- **Key hygiene**: `ZEN_API_KEY` env only. Never printed, never stored,
  never a flag (flags leak into process tables).

## How it works in detail

1. **TCP dial** (`-addr` override or `host:443`).
2. **uTLS handshake** with a `HelloCustom` spec replicating the
   captured genuine-CLI profile byte-for-byte (verified via localhost
   CONNECT-proxy capture, 2026-09-20): 17 ciphers, no GREASE; 14
   extensions in fixed order
   (`SNI EMS reneg curves points ticket ALPN status sigalgs SCT
   keyshare pskmode versions padding`); ALPN `http/1.1` only; groups
   X25519/secp256r1/secp384r1; sigalgs Chrome-order + SHA1-RSA;
   X25519 keyshare auto-generated; BoringSSL padding; **no**
   compress-cert, **no** ALPS, **no** ECH.
3. **Hand-framed HTTP/1.1**: request line + headers written in the exact
   CLI order/casing (Authorization, Content-Type, User-Agent,
   x-opencode-client/project/request/session, Connection, Accept, Host,
   Accept-Encoding, Content-Length) + raw body bytes. No header
   normalization, no chunked upload, keep-alive.
4. **Sequencing**: with `-pre`, the first request (title call shape)
   goes out, its full response is drained, then the main request goes on
   the **same connection** — replicating the CLI's title→main pattern.
5. **Response drain**: status line printed; headers parsed for
   Content-Length vs chunked; chunked SSE bodies drained (cap 200KB)
   with the first 300 bytes printed (`PRE BODY-HEAD` / `MAIN BODY-HEAD`).

## What it proved (honest status)

With byte-identical handshake + byte-identical 91.6KB bodies + identical
headers + same-connection sequencing, zencli gets title-401 (matches the
CLI) and main-**403** where the CLI gets 200. Every observable network
layer was eliminated by this instrument — the gate's discriminator is
outside the reconstructible request. zencli therefore does **not** pass
the gate today and is kept as: (a) the proof instrument behind verdict
v3/v4, (b) a ready client if the gate ever changes, (c) a template for
non-gated endpoints.

## How it works with pi

It doesn't — deliberately. pi talks to zen through its own provider, not
through zencli:

- **Blessed path**: pi's `opencode-zen-free` provider
  (`pi-opencode-direct@0.1.6`) speaks HTTPS directly to zen with full
  CLI identity headers over the Bun stack — and passes the gate
  (`PI-ZEN-DIRECT`, exit 0, 2026-09-20). No keeper hop, no subprocess,
  no zencli involved. Same backing key (RETIRED_1) as the CLI.
- **zencli's relationship to pi** is evidentiary, not operational: it
  established *why* the keeper relay fails (identity stripped upstream)
  and *that* a reconstructed request cannot pass, which is what pointed
  back to verifying the direct provider.
- **If you ever need pi to drive zencli** (e.g. gate changes and only
  raw-wire control passes): wrap it as a local subprocess bridge
  (`ZEN_API_KEY` from the same stored credential pi uses), same pattern
  as the existing `pi-zen-bridge` CLI-subprocess bridge. Not wired today
  because the direct provider already works — don't add moving parts
  without a failing receipt.
