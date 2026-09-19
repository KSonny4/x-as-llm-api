# Dispute plan: big-pickle via CLI — local works, cluster shows down

## The dispute (stated plainly)

- User-observed: opencode CLI + big-pickle works on the laptop.
- Keeper shows: all zen routes down on the cluster, including big-pickle.
- My claim ("quota exhaustion from ~180 runs") was an **inference from
  timing patterns, not from error text**. Dispatch logs record only
  `-> degraded/down`, never the L2 error body. I have NOT seen a single
  cluster-side CLI error string. If the cluster path is broken (auth,
  egress, binary), the symptom looks identical to quota drain from where
  I stood. That is the gap, and the user's challenge is legitimate.

## What is already on record (checkable, not re-asserted)

- `docs/zen-parity.md`: keyed `/models` 200 laptop + cluster, same key,
  same minute (fresh, low-cost, no quota burn).
- `docs/zen-egress-receipts/matrix-zen.json`: 9 degraded + 1 down with
  `checked_at` (morning sweep, cluster L2 passed then).
- Dispatch `8cfda13f` logs: 89 reported, 0 failed (states only, no bodies).
- Missing: any cluster CLI error text; any big-pickle-specific local CLI
  transcript dated today.

## Decisive experiments (cap: max 3 cluster CLI calls, no full sweeps)

1. **Reproduce local NOW.** Run big-pickle via laptop opencode CLI, one
   prompt, save transcript + timing. Proves "works local" is current,
   not morning memory. Cost: 1 local call. No cluster impact.
2. **Read the actual cluster error text.** Single-route cluster dispatch
   (1 zen route, big-pickle spare key, trimmed seeds) OR, cheaper first,
   check whether `probe/worker.py` already logs L2 error bodies and
   whether keeper's stored `probe_detail` (text[:200]) is retrievable.
   If neither surfaces the body, add error-text to the dispatch log
   line only (logs, not matrix JSON — shape stays frozen). Cost: 0–1
   cluster calls.
3. **Same key, same prompt, both sides.** If step 2 shows a quota string
   (429/FreeUsageLimitError), the dispute is settled: quota, with quoted
   evidence. If it shows auth/config/egress failure, the user is right:
   the cluster path is broken — pivot to root-causing the path (node
   auth snapshot age vs laptop login is suspect #1; egress is suspect
   #2, already disproven for HTTPS but not re-proven for CLI).

## Success criteria

- Both transcripts + the cluster error string quoted side by side.
- Verdict in one sentence: quota (with string + timestamp) OR broken
  path (with failing component named). No inference words.
- Loser (my quota claim or the broken-path suspicion) is withdrawn in
  the journal, with the receipt linked.

## Rules for this investigation

- No full-sweep dispatches. No commits until the user approves this plan.
- Every claim cites a file + line or a log line. No timing-pattern
  arguments presented as conclusions.
- Quota burn budget: 1 local + max 3 cluster CLI calls, then stop and
  report regardless of outcome.
