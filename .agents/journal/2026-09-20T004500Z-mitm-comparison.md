# 2026-09-20 — MITM comparison: laptop vs Nomad docker opencode traffic

Question: what differs between laptop CLI (works) and Nomad docker CLI?
Method: metadata-only observer proxy (scripts/mitm-log.py — SNI, cipher
fingerprint, ALPN, byte counts, timing; never header values/bodies).
Both legs through the same proxy => same egress, controlled experiment.

## Laptop leg (native binary, MUSE-LOCAL/MUSE-MITM, ~6s, exit 0)
- models.opencode.ai:443 — 17 ciphers / 4b3b85888c4b, SNI ok, http/1.1,
  402B up / 339,889 down
- opencode.ai:443 — same fingerprint, 93,801 up / 154,956 down

## Nomad leg (probe-shell alloc, MUSE-MITM-NOMAD, 12s, exit 0)
- models.opencode.ai:443 — SAME fingerprint, 402 up / 339,764 down
- opencode.ai:443 (x2) — SAME fingerprint, smaller byte totals
- DNS both sides: opencode.ai = 172.65.90.22 (identical)

## Verdict
NO client-side difference. Same binary + same auth bytes + same TLS
handshake + same SNIs + same DNS = same answers. 12s vs 6s is tunnel
RTT (Nomad→laptop→internet), not behavior. Earlier failures each have
their own receipt: 256MB SIGKILL (rc=-9), quota 429s/timeouts, one
empty-auth staging (my register bug, "Killed" red herring — healthy
with correct auth). Nothing cryptic remains on this path.
Receipts: /tmp/mitm.log (local only, not committed — contains targets),
scripts/mitm-log.py (the instrument).
