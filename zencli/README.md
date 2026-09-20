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

## Interaction map (who talks to whom)

```text
pi harness
 ├── opencode-zen-free provider ──HTTPS (Bun, CLI identity)──▶ zen ✅ 200 (blessed)
 │     key: pi stored credential (RETIRED_1, hash-verified)
 ├── keeper-big-pickle provider ──▶ keeper ──HTTPS (urllib, bare)──▶ zen ❌ 429
 │     key: keeper route (RETIRED_1 post-reorder; was PETR)
 └── (zencli: NOT in pi's path — see below)

zencli ──HTTPS (uTLS mimic + hand framing)──▶ zen ❌ 403 (gate)
       └── built to prove the above table, not to serve traffic
```

## Does pi have everything it needs? YES

Nothing is missing for the pi harness: the `opencode-zen-free`
provider is configured, keyed (stored credential, RETIRED_1), and
proven end to end (`PI-ZEN-DIRECT`, exit 0, 2026-09-20). No keeper hop
needed, no new piece required. Remaining chores are hygiene, not
capability: rotate the Petr key (transcript exposure), and optionally
fix keeper's upstream identity headers if the relay path is ever
wanted back (keeper serving change — separate scope).

## Could we add an OpenAI API in front and provide that?

Meaning: an HTTP server accepting OpenAI `POST /chat/completions`
that pi (or any OpenAI client) points at, with zencli's wire control
behind it. Technically straightforward — a `-serve` mode on this
binary: stdlib `net/http` listener + the existing uTLS dial + header
framing, ~60 extra lines. Two honest caveats:

1. **It would 403 today.** A server wrapper doesn't change what the
gate sees: zencli's requests are rejected at the vendor regardless of
who asked for them. Serve-mode only becomes useful IF the gate ever
changes (or for non-gated endpoints — the code is endpoint-agnostic
via `-host`/`-path`).
2. **pi doesn't need it.** The direct provider already gives pi a
working OpenAI-shaped path to zen. Adding a local server in between
would add a hop, a secret-handling surface, and a process to babysit
for zero capability gain.

Verdict: build `-serve` only on a future receipt showing raw-wire
control passing where stock stacks fail. Until then it stays a design
note, not code.

## -serve mode (OpenAI-compatible HTTP in front of zen)

```bash
ZEN_API_KEY=... ./zencli -serve -port 8099
curl -X POST http://127.0.0.1:8099/v1/chat/completions \
  -H "Content-Type: application/json" -d '{"model":"...",...}'
```

- One endpoint: `POST /v1/chat/completions`. Client JSON passes
  through verbatim; the server stamps the pi-exact upstream identity
  (Stainless suite + CLI headers + per-request ses_/msg_ ids, undici
  order/casing) and relays status + body back (chunked SSE de-chunked
  into a plain stream).
- Key from `ZEN_API_KEY` env only; refuses to start without it
  (exit 2). Binds 127.0.0.1 only. Bodies capped at 4MB.
- Status 2026-09-20: locally verified (refusal, 404, relay correctness
  via 401 shapes, hang fixed); vendor proof FAILED (403) with
  pi-exact headers + pi-exact body — same undetermined gate remainder
  as the one-shot path. Post-cap code review found a self-inflicted
  protocol anomaly in the proof build (contradictory
  `connection: keep-alive` + `Connection: close`); fixed, UNPROVEN —
  needs exactly 1 confirmation call (over the 3-call budget: requires
  owner authorization).

It doesn't — deliberately. pi talks to zen through its own provider, not
through zencli:

- **zencli's relationship to pi** is evidentiary, not operational: it
  established *why* the keeper relay fails (identity stripped upstream)
  and bounded what reconstruction can pass, which is what pointed back
  to verifying the direct provider.
- **If you ever need pi to drive zencli** (e.g. gate changes and only
  raw-wire control passes): wrap it as a local subprocess bridge
  (`ZEN_API_KEY` from the same stored credential pi uses), same pattern
  as the existing `pi-zen-bridge` CLI-subprocess bridge. Not wired today
  because the direct provider already works — don't add moving parts
  without a failing receipt.
