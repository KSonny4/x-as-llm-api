# Zen down-vs-CLI diagnosis (M2, READ-ONLY) — 2026-09-19

Question: both live Zen routes read `down` (`l1=suspect`, in-cluster
`l2=fail`) while the laptop opencode CLI works. No reseeds, re-logins,
or dispatches were run; matrix JSON hash identical before/after
(`aaeb5885ae95fa9e`). No credential values appear below.

## Evidence (quoted)

1. Laptop `opencode auth list` → `OpenCode Zen ● api` (working CLI
   credential present). Laptop `auth.json` (Sep 16, 458 bytes) holds
   provider sections `deepseek, nvidia, opencode, opencode-go` — the Zen
   login rides the CLI's own auth, not a `zen` section.
2. Node side: `keeper-probe.nomad.hcl:13,35,67` bakes
   `-var=opencode_auth_json` (a copy of the laptop file at deploy time)
   into the alloc (`probe/entry.sh:6-9` copies it to
   `~/.local/share/opencode/auth.json`). Node snapshot may predate the
   working laptop login.
3. No-credential reachability split: `GET /zen/v1/models` from the
   laptop → `200`; the SAME request from inside the keeper alloc →
   `HTTP 403 Forbidden` (DNS/TLS fine both sides). Cluster egress to
   Zen is policy-denied at IP/WAF level independent of any key.
4. History: all 8 retired keys self-report `probe: dead:429` — Zen
   throttles this fleet aggressively.

## Verdicts

- `zen/big-pickle` (petr1kubelka) — **node-side denial**, not key-dead:
  L1 fails from the cluster while the identical URL answers 200 from
  the laptop (evidence 3); L2 fails on a possibly-stale Sep-16 auth
  snapshot while the laptop CLI lists a working Zen credential
  (evidence 1+2). L2 error text is not retained anywhere
  (`dual_verdict` collapses it to `fail`), so the L2 leg cannot be
  subdivided further without a fresh dispatch (explicitly deferred).
- `zen/big-pickle-spare` (ksonny4) — **same verdict, same evidence**.
- Retired 1..8 — **key-dead by own metadata** (`expired-gateway`);
  placeholders stay `unknown`, correctly never probed.

## Follow-up (not this goal)

Refresh the node's opencode login from current laptop auth, re-dispatch,
capture resulting states. That is an auth write + state rewrite —
outside the read-only mandate; do it as its own step with receipts.
