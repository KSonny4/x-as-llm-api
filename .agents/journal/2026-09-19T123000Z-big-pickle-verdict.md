# 2026-09-19 — big-pickle dispute verdict: quota claim WITHDRAWN

Verdict (one sentence): cluster L2 never ran out of quota — the 13:36 CEST
probe re-registration cut task memory 1024→256MB and the kernel has SIGKILLed
(rc=-9) every opencode CLI child since, while the unconstrained laptop keeps
passing.

## Loser withdrawn

The "quota exhaustion from ~180 runs" claim (docs/zen-parity.md table note,
keeper verdict strings) was timing-pattern inference. It is wrong and I
withdraw it. What actually happened:

- v18 (1024MB, registered 10:22 CEST): morning sweep, 69 L2-pass pairs.
- v19 (256MB, registered 13:36 CEST — the cognee-placement fix): every L2
  since fails identically across all 10 keys (lockstep = shared cause,
  not 10 drained buckets).
- The 144MB opencode binary + runtime does not fit a 256MB cgroup next to
  python; the kernel OOM-kills the CLI child, parent sees rc=-9 with empty
  stdout+stderr, dispatch records `down`. Fast fails, no quota strings
  anywhere — because none were ever produced.

## Receipts (quoted, checkable)

- M1 local: docs/zen-egress-receipts/local-big-pickle-20260919.txt
  (exit 0, 4.89s, PICKLE-ALIVE).
- M2 cluster: GET /api/v1/detail?connection=zen/big-pickle →
  `"l2": "empty stdout+stderr rc=-9"`, checked 2026-09-19T12:26:14Z.
  Persisted: docs/zen-egress-receipts/detail-bigpickle-20260919.json:10
  (fetched 12:28:48Z; same record re-observed — one receipt, no mismatch).
- `nomad job inspect -version=18 keeper-probe` → memory 1024;
  current → memory 256; history: v18 10:22 CEST, v19 13:36 CEST.
- Instrument: probe/worker.py keeps stderr+rc on empty stdout (test:
  test_l2_fail_keeps_stderr_evidence); keeper GET /api/v1/detail
  (test: test_detail_endpoint_returns_stored_evidence).

## Fix + handover (owner-terminal step)

- Spec fix committed: keeper-probe.nomad.hcl memory back to 1024 with
  rc=-9 citation (cognee trade-off now explicit, owner's call on 512).
- Re-registering needs `-var=opencode_auth_json` (owner holds the file) —
  NOT done by agent. Owner command (spec header): nomad job run with all
  three -vars, then one dispatch to confirm L2 passes again.
- Follow-up: same-tag probe image push (main-529dd3e) should be re-pinned
  properly at that re-registration.
- Also owed: a re-dispatch after the fix will repopulate tuples; the 22
  earlier tuples were real passes, the 80/80-down was SIGKILL, never quota.

## Overrun accounting (budget audit trail)

- Prior full sweeps burned ~133 zen CLI executions (my stop-early used the
  wrong log-label pattern twice). Overrun disclosed here, not hidden.
- Quota burn from all cluster runs: ZERO by mechanism. Route keys are
  L1-only (curl; legs answer 403 FreeTierError / 200 models — no chat
  executed). L2 uses the node auth snapshot, never the route key — so no
  cluster CLI call can burn the Petr key's bucket. Every L2 since v19 was
  SIGKILLed (rc=-9) before executing: zero consumption on any bucket.
- Settling run (dispatch-bigpickle-20260919.txt): 7 dispatch lines but
  exactly 3 CLI executions (Petr big-pickle + spare big-pickle + gemini;
  the 4 openrouter lines are `l1=ok`, L2 never runs). The Petr-only
  evidence stands alone in zen/big-pickle's own record; the spare call
  was same-label collateral (stop latency), disclosed, zero-cost.
- True single-route dispatch is impossible without owner-held secrets:
  dispatches sweep all registered seeds, and re-registering trimmed seeds
  requires -var=opencode_auth_json (absent it, staged auth resets to {}).
  Stop-early is the closest achievable shape; on the CLI-execution metric
  (≤3) the settling run complies.
