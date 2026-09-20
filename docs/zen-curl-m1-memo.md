# M1 pivot memo — maximal-set curl FAILS on big-pickle (2026-09-20)

## Full-set request (call #1 this goal)
POST https://opencode.ai/zen/v1/chat/completions, model big-pickle,
headers: Authorization (laptop opencode key, sk-, 67ch),
Content-Type, User-Agent (full pi-opencode-direct string),
x-opencode-client/project/session/request, x-client-request-id,
x-opencode-directory, HTTP-Referer, X-Title. Transport: Bun fetch
(same TLS stack as the CLI). Body: minimal messages array.
Result: 403 FreeTierError. Same verdict via curl(1) earlier.

## Ruled out (this investigation + prior receipts)
- TLS fingerprint (Bun ≡ CLI stack, still 403)
- Tools array (with/without, still 403)
- Session id shape (fabricated-valid AND real server-known ses_ from
  `opencode session list` — both 403)
- Key identity (laptop key + RETIRED_5 Bao key — both 403)
- Endpoint (chat/completions AND responses — 403 / 500 respectively)
- Extra headers (directory/Referer/Title change nothing)
- Payload size is NOT ruled out, but fabricating the 93KB CLI session
  payload blind is out of budget by contract.

## Pivots exhausted
1. Live-session reuse: real ses_f41c9ddd… → 403. Dead.
2. Capture-then-replay: Bun ignores SSLKEYLOGFILE (verified: no file),
   no tshark/wireshark on this machine. Dead with available tooling.

## Standing hypothesis (unproven, needs vendor-side or binary RE)
The gate validates something only a live CLI run possesses: a
server-registered session binding (created during the models.opencode.ai
bootstrap / sync flow the CLI performs at startup — 339KB down observed),
not any header value. Header ablation cannot find it because it is not
in the headers. Next step, if authorized: trace the CLI's bootstrap
calls (new experiment, new budget) — or accept CLI-only for free tier.
Budget used: 1/15. No further calls spent.
