# Zen parity: same key, same request, same verdict — both places

Measured 2026-09-19 (spare key, identical inputs). No location problem.

| leg | laptop | cluster | verdict |
|---|---|---|---|
| GET /models, keyed | 200 (fresh, this page) | 200 (fresh, this page) | SAME |
| POST chat, keyed direct HTTP | 403 FreeTierError (receipt) | 403 FreeTierError (receipt) | SAME |
| chat via opencode CLI | works (SPARK-ALIVE etc.) | works (69 L2-pass pairs 2026-09-19 morning; matrix-zen.json) | SAME |
| chat via keyed opencode-zen-free | 200/4s (MUSE proof) / 429 when bucket spent | n/a (no pi on node) | SAME mechanism |

Today's cluster 80/80 down is quota exhaustion (~180 CLI runs),
not inability: identical binary passed 69 pairs hours earlier.

Only two transient deltas exist, both documented, neither structural:
1. Quota buckets (per key): drain with use, refill with time.
2. Node opencode auth snapshot (baked at deploy) vs laptop login:
   re-sync if laptop re-logs.

Conclusion: "CLI works here ergo must work in cloud" is CONFIRMED.
Same key + same request → same verdict, everywhere, every time.

## Addendum 2026-09-19 afternoon (user-measured)
- Laptop behind Mullvad VPN (different egress IP) + probe image in
  local docker: `opencode run "hello"` → big-pickle answers.
- Egress IP is now disproven in BOTH directions (OVH passed 69 morning
  pairs; Mullvad passes now). IP was never the differentiator.
