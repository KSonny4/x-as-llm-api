# PR4 live loop artifacts (2026-09-18, dispatch 10daf8ef, keeper v10)

Proves the Nomad dispatched probe runs L2 in-cluster and the matrix
refresh shows fresh verdicts. Redaction-audited: no bearer/api_key
material (checked for 40+ char tokens, api_key values, Bearer literals).

- `pr4-dispatch.log` — probe alloc log: openrouter L1-ok (no L2, correct
  on-demand behavior), zen big-pickle L1-suspect → L2 pass → `degraded`,
  both POSTs `202` (`2 reported, 0 failed`).
- `pr4-matrix.json` — `GET /api/v1/matrix?refresh=1` after ingest:
  `diagnostics.divergent == ['zen/big-pickle']`.
- `pr4-metrics.txt` — `GET /metrics`: divergent gauge 1 (zen) / 0
  (openrouter) with fresh `checked_at` timestamps.
- `pr4-smoke.log` — in-alloc `smoke.py` on keeper v10: SMOKE GREEN.
