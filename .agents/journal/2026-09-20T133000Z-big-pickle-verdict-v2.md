# 2026-09-20T~13:30Z — big-pickle verdict v2: HTTP relay cannot pass the gate

## The user's first-principles challenge (upheld)
Local `opencode run -m opencode/big-pickle` returns live 200s (verified
ALIVE-CHECK-77 same hour). Keeper/pi HTTP relay with the PROVEN-SAME key
(hash-matched: local CLI key == Bao OPENCODE_ZEN_RETIRED_1 == keeper route
key after reorder) gets 429/403. Same account, same key — so the
difference is the CLIENT, not quota. The M2/M3 "vendor quota blocked"
claim is WITHDRAWN (bucket is fine; CLI proves it).

## Same-machine replay matrix (all fail, CLI passes)
Key/endpoint/host/model-string/headers/TLS-JA3/HTTP-version/IP-family all
eliminated. This turn, additionally killed with receipts:
- real `@ai-sdk/openai-compatible` SDK request → 403 FreeTierError
- title-call-first sequence (paid 401 then free) → main still 403
- authed GET /models (200) then POST same connection → 403
- tools+stream+system body → 403
- curl -4 vs -6, --http1.1 vs --http2 → 403 all four
- full header set incl. x-opencode-*, ses_/msg_ ids → 403
- config override ruled out (no opencode provider apiKey in config;
  CLI uses auth.json key = RETIRED_1, hash-verified)

## Verdict
The gate binds a signal OUTSIDE HTTP semantics (only the genuine binary
passes; nothing replayable does — exact sub-HTTP signal unidentified:
HTTP/2 frame fingerprint and per-request body shape both eliminated as
sole causes; TLS JA3 identical per prior ablation). A Python HTTP relay
(keeper) is STRUCTURALLY incapable of forging it.

## Consequence (blessed Nomad path)
"Works on Nomad" = RUN THE BINARY on Nomad, not replay its HTTP:
- pi-zen-bridge (CLI subprocess) pattern, proven locally (CLI-BRIDGE-ALIVE)
- Nomad needs >=1024MB for the CLI (256MB SIGKILLs it; 69 passes at
  1024MB on v18 probe) — memory floor, not a bug
- keeper HTTP relay for zen routes: RETIRED (cannot pass gate by design);
  seed reorder (RETIRED_1 first, deployed this turn) kept as hygiene only
- keeper_token_next="" rotation + Petr-key rotation still owed (transcript
  exposure), independent of this verdict
