# Zen L1 egress (M1–M3) — 2026-09-19

Root cause (proven): Zen's edge (Cloudflare-fronted: `opencode.ai` →
`172.65.90.x`) 403-denies OVH egress. Same keys + same
`/zen/v1/models` URL → laptop `200`, keeper alloc `403` (keyed and
keyless alike). Full proof: `docs/zen-diagnosis.md` addendum.

## M1: userspace Mullvad sidecar (parked, not deleted)

Pin (public relay facts): `de-fra-wg-004`, endpoint
`185.209.196.74:51820`, pubkey
`tzYLWgBdwrbbBCXYHRSoYIho4dHtrm+8bdONU1I8xzc=` — the SAME relay
Pi gluetun currently exits (`185.209.196.155`, Frankfurt), through
which Zen returned `200 OK` no-creds. Receipts:
`docs/zen-egress-receipts/sidecar-routing.txt`,
`docs/zen-egress-receipts/escrow-validation.txt`, image
`registry.pkubelka.cz/keeper-egress:main-dfbc2f1`
(`sha256:57e73f2cb77eb1376259d6c8f2d4739f30f7773bc68f62b84b1e406b61abfac1`).

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

## Final: free-tier key policy, not the network (2026-09-19)

Quoted from Zen itself (identical on laptop, keeper alloc, probe image):
`403 {"type":"error","error":{"type":"FreeTierError","message":
"OpenCode's free tier can only be used from within OpenCode"}}` — on
`POST /zen/v1/chat/completions` with a free-tier key over direct HTTP.
`GET /zen/v1/models` returns 200+models with the fleet UA; only the
chat leg is tier-denied. The opencode CLI (L2) passes because it IS
"within OpenCode". Verdict `degraded` is therefore the CORRECT honest
state for these keys — reachable, key valid, direct chat refused by
key-tier policy. No egress change can fix policy; the Mullvad sidecar
(key conflict, parked), the CF worker (adopted then parked — it only
moves the same denied request), and the IPv4 pin (removed again —
address family was never the factor) are all recorded above as
eliminated hypotheses with their evidence. What ships: fleet UA
(`FLEET_UA`, models leg 200) + this documentation.

## Key handling

Mullvad private key + addresses: Bao
`pi-infinity-llm/MULLVAD_WIREGUARD_KEY` only (shape-validated, never
displayed). No key material in git (tripwire clean).
