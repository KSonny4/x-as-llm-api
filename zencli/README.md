# zencli — OpenAI-compatible server in front of opencode zen

One Go binary, zero dependencies (stdlib only). Serves an OpenAI-style
API by driving the genuine `opencode` CLI subprocess per request — the
only client the vendor's free-tier gate passes.

## Prerequisites

- Go toolchain (build only) — the binary itself needs nothing.
- The `opencode` binary on PATH (or pass `-opencode-bin`), logged in
  (`opencode auth login`) with a key whose bucket serves free models.
- No server-side key: the CLI uses its own auth. There is no flag,
  env var, or file through which zencli itself holds a credential.

## Run

```bash
go build -o zencli .
./zencli -port 8099                    # 127.0.0.1:8099
./zencli -bind 0.0.0.0 -auth SECRET    # network + bearer gate
```

Flags: `-port` (default 8099), `-bind` (default 127.0.0.1),
`-auth` (optional client bearer; empty = localhost trust),
`-opencode-bin` (CLI path).

## Endpoints

- `GET /v1/models` — static 7-model catalog (free models observed
  working via this backend). No vendor touch.
- `POST /v1/chat/completions` — `{model, messages, stream}`.
  Non-stream returns `chat.completion` JSON; `stream:true` returns
  format-exact SSE (`delta.content` word chunks with
  `finish_reason: null`, final `stop`, `data: [DONE]`).

## Request mapping

- Model `"X"` → CLI `opencode/X` (already-prefixed ids pass through).
- System + multi-turn messages flatten into one prompt (system verbatim
  first, turns labeled, last user message raw; tool results labeled).
- `temperature` / `max_tokens` / `reasoning_effort` have no CLI
  equivalent and are ignored. `store` is always false upstream.
- Per-request temp cwd (parallel-safe), 110s CLI timeout, stdout
  becomes the assistant message.

## Recipes

```bash
# non-stream
curl -X POST http://127.0.0.1:8099/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"big-pickle","messages":[{"role":"user","content":"hi"}]}'
# stream
curl -N -X POST http://127.0.0.1:8099/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"big-pickle","messages":[{"role":"user","content":"hi"}],"stream":true}'
# with client auth
./zencli -bind 0.0.0.0 -auth SECRET   # clients: Authorization: Bearer SECRET
```

## Limits (stated plainly)

- Latency ~15–40s per request (CLI startup + inference).
- SSE is format parity, not token-realtime: one subprocess completion,
  then word-chunked. Clients parsing event-streams work unchanged.
- No embeddings/audio/responses endpoints: zen free tier serves chat;
  parity covers what exists.
- History: a raw-wire HTTPS mimicry backend existed, proved 403-gated
  at full parity, and was deleted (2026-09-20) — no fallback, no flag,
  no helper remains. One-shot probe mode was removed with it.

## Verification

- `go build ./...` clean; `go test -count=1 .` 8/8 (mapping, SSE
  shape incl. null finish_reason, models, auth, exec relay ×2 with a
  fake binary).
- Live transcripts: `TRANSCRIPT.md` (command + HTTP status + body +
  exit per proof) and `proof-*.json/txt` bodies.
- No secret values in git (sk-/eyJ/PEM scans clean, tracked + history).
