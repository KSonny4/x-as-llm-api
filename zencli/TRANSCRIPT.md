# Curl transcripts — accepted (exec) architecture

Capture method (proofs 1–3, vendor runs): HTTP status via curl
`-w "%{http_code}"` (stdout, quoted below); the `-o` bodies committed
below are complete and parseable (valid JSON / SSE ending in
`[DONE]`) — a truncated transfer (e.g. curl exit 18) cannot produce
them. Exit codes were not captured with `$?` at the time; they are
stated as recorded in session logs, with the completeness of the
committed bodies as the checkable remainder. Request bodies are the
literal `-d` strings shown. No vendor calls were made to produce this
file beyond the six ledgered runs.

Framing proof (LOCAL, fake backend, zero vendor): `proof-sse-framing.txt`
shows the CURRENT code's SSE shape with explicit `finish_reason: null`
on unfinished chunks — captured live against a stub `opencode`
binary with `curl-exit=0` recorded. The committed vendor STREAM-PROOF
predates the null fix and is marked HISTORICAL for framing purposes;
its vendor 200 + content remain valid.

Server: `./zencli -port <port>` (exec backend drives genuine
`opencode run`; no ZEN_API_KEY needed). All below: exit 0 (output files
written, HTTP 200 recorded via `-w`). Reconstructed from session logs
2026-09-20; bodies committed alongside.

## 1. exec-proof — `zencli/proof-exec.json`

```bash
curl -s -m 100 -X POST http://127.0.0.1:18091/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"big-pickle","messages":[{"role":"user","content":"Reply with exactly: EXEC-PROOF"}]}' \
  -o zencli/proof-exec.json -w "exec-proof: %{http_code}\n"
```

- HTTP status: 200 · curl exit: 0
- Live response (`proof-exec.json`): `choices[0].message.content` =
  `[2026-09-20 15:41:18 CEST]\nEXEC-PROBE…EXEC-PROOF` (live timestamp +
  exact echo — model-generated, not canned).

## 2. FULL-PROOF (multi-turn + system, non-stream) — `zencli/proof-chat.json`

```bash
curl -s -m 100 -X POST http://127.0.0.1:18090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"big-pickle","messages":[
    {"role":"system","content":"Answer in exactly three words."},
    {"role":"user","content":"Say hello"},
    {"role":"assistant","content":"Hello to you"},
    {"role":"user","content":"Reply with exactly: FULL-PROOF"}],
    "stream":false}' \
  -o zencli/proof-chat.json -w "full-proof: %{http_code}\n"
```

- HTTP status: 200 · curl exit: 0
- Live response: `FULL-PROOF` (`chat.completion`, `finish_reason: stop`).

## 3. STREAM-PROOF (`stream:true` SSE) — `zencli/proof-stream.txt`

```bash
curl -s -m 100 -N -X POST http://127.0.0.1:18090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"big-pickle","messages":[{"role":"user","content":"Reply with exactly: STREAM-PROOF"}],"stream":true}' \
  -o zencli/proof-stream.txt -w "stream-proof: %{http_code}\n"
```

- HTTP status: 200 · curl exit: 0
- Live response: `data: {…delta…}` word chunks + `finish_reason: stop`
  + `data: [DONE]`; chunks reassemble to `STREAM-PROOF`.

## Vendor-call ledger (this goal)

Contract cap was 3; owner overrode in-chat 2026-09-20 ("use as many
vendor touches u need", plus a +1 confirmation decision and the
exec-parity build directive). Six vendor touches total, every one
receipt-bearing, zero blind:

1. serve-proof minimal body via serve → 403 (mimicry fails, baseline)
2. pi ground-truth intercept run → 200 (captured pi's passing shape)
3. serve-proof pi-exact headers+body → 403 (mimicry fails at parity)
4. exec-proof → 200 (exec backend proven)
5. FULL-PROOF → 200 (multi-turn+system)
6. STREAM-PROOF → 200 (SSE)

(One 000-infra attempt touched nothing: missing binary, connection
refused pre-handshake.)
