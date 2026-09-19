# Zen L1 egress (M1–M3) — 2026-09-19

Root cause (proven): Zen's edge (Cloudflare-fronted: `opencode.ai` →
`172.65.90.x`) 403-denies OVH egress. Same keys + same
`/zen/v1/models` URL → laptop `200`, keeper alloc `403` (keyed and
keyless alike). Full proof: `docs/zen-diagnosis.md` addendum.

## M1: userspace Mullvad sidecar (parked, not deleted)

- `probe/egress/`: sing-box (WireGuard endpoint + HTTP CONNECT
  `127.0.0.1:8888`), zero privileges (Nomad denies `net_admin`, so no
  kernel TUN — measured). Route rules sent only `opencode.ai` into the
  tunnel; proxy + routing verified working in alloc logs
  (`endpoint/wireguard[mullvad-ep]: outbound connection`).
- sing-box ≥1.11 schema note: WireGuard lives in `endpoints`, referenced
  DIRECTLY from route rules (`"outbound": "<endpoint-tag>"`) — no
  outbound wrapper exists (`outbounds[].endpoint` and
  `route.rules[].endpoint` are both invalid; `sing-box check` confirms).
- Image: `registry.pkubelka.cz/keeper-egress:main-dfbc2f1` (pushed).
- PARKED because: the sidecar reused the Pi gluetun key+address
  (`10.69.30.235/32` on both) → Mullvad-side session conflict →
  blackhole (connections enter the endpoint, nothing returns, zero
  errors). Evidence: identical tunnel address on Pi (`ip addr`) and Bao.
- Revive path: register a SECOND Mullvad key on the same account, escrow
  as `MULLVAD_WIREGUARD_KEY_PROBE`, re-add the sidecar. Blocked on:
  same-account proof + a device slot (5/5 used) — owner decisions.

## M3: Cloudflare Worker (ADOPTED)

- `probe/egress/worker.js` → `keeper-zen-egress` on
  `keeper-zen-egress.kubelkatropkova.workers.dev`: forwards `/zen/*` to
  `https://opencode.ai`, nothing else (other paths `404`).
- Captured: keyed `200`, keyless `200`, bad-path `404`.
- Adoption: `ZEN_BASE` in `scripts/render-seeds.sh` points at the worker
  (per-route base URL — no probe code change).
- Trade-off (accepted): Cloudflare sees the per-request `Authorization`
  header in transit; nothing is stored at CF. The worker is public but
  useless without the caller's own key.

## Key handling

Mullvad private key + addresses: Bao
`pi-infinity-llm/MULLVAD_WIREGUARD_KEY` only (shape-validated, never
displayed). No key material in git (tripwire clean).
