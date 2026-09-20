# Ablation ledger — big-pickle curl vs CLI gate (2026-09-20, budget 15)

Format: step | change vs previous | verdict. All calls local Bun/Node,
laptop key unless noted. CLI baseline exits 0 throughout.

1. FULL maximal set (doc headers + directory + Referer + X-Title, full UA) → 403
2. doc-only set (minimal documented) → 403
3. +tools +stream:true +max_tokens → 403
4. exact id.ts timestamp ids (was random) → 403
5. spare Bao key (was laptop key; R5 also tried) → 403
6. +x-session-affinity +session_id (pi-ai core headers) → 403
7. byte-identical openai-SDK path (Stainless headers incl.) → 403
8. live server-known ses_ id (was fabricated) → 403
9. post-quota-reset retry (00:30Z window passed) → 403

Untried (out of budget, listed honestly): x-opencode-sync/ticket/title
(no known values), system-prompt parity, openai-directory canonical path.

Conclusion: no client-observable variable flips the verdict. The gate
input is server-side (session binding created in a flow no bare request
reproduces). curl-alone cannot pass; the script path needs the CLI's
bootstrap sequence, whose wire shape is not recoverable with available
tooling (no keylog, no plaintext capture).
Calls used: 9 this goal + 4 pre-goal shape probes = 13 total ≤ 15.
