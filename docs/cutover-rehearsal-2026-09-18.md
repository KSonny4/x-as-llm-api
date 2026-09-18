# Cutover rehearsal + KEEPER_TOKEN rotation — 2026-09-18

Goal: rehearse Nomad revert forth/back with smoke both ways, then rotate
`KEEPER_TOKEN` (recorded 403) with parallel-accept until smoke green.
No secret values below — tokens referenced by Bao version only.

## Cluster facts (discovered)

- Nomad: `https://nomad.pkubelka.cz`, single node `ovh-vps` (57.129.155.203),
  ACL via `secret/projects/NomadSetup/acl` (management). No Vault/Consul →
  bearer reaches allocs via task env (holder: Nomad management token only).
- Registry: `registry.pkubelka.cz` (Bao `NomadSetup/registry` creds).
- No SSH (Cloudflare Access needs interactive SSO); no origin IP in DNS
  (all proxied). Smoke runs **in-alloc** (`nomad alloc exec … smoke.py`):
  no published port, token never leaves the cluster.
- Public `keeper.pkubelka.cz` serves **v1-freeze** packs (old deployment);
  hostname cutover is a later item — untouched here.

## Rehearsal (job `keeper`, image `registry.pkubelka.cz/keeper:cutover-1)

| Job ver | Spec | Smoke (in-alloc smoke.py) |
|---|---|---|
| v0 | first run, old token | FAILED — image missed `aa`/`translate`/`matrix` modules (exit 1). Fixed Dockerfile, `force_pull=true` |
| v1 | fixed image, old token | GREEN 16/16 (alloc 26612fb6) |
| v2 | + `KEEPER_TOKEN_NEXT` (parallel-accept) | GREEN 17/17, NEXT 200 (alloc ee3202c3) |
| v3 | `nomad job revert keeper 1` | GREEN, NEXT-as-OLD 401 — revert provably restored old-only auth (alloc 083c95e6) |
| v4 | re-apply v2 spec | GREEN 17/17, NEXT 200 (alloc b4e8e690) |
| v5 | token=new only, NEXT="" | GREEN 17/17: new 200, old (Bao v1) 401, wrong 401 (alloc ca915677) |

Revert forth/back: v2 → v3 → v4, smoke green all three ways. Full per-gate
logs: operator kept `/tmp/smoke-v{2,3,4,5}-*.log` (17/17 ok-lines each).

## Rotation

- New token: `openssl rand -hex 32`, proved via parallel-accept (v2/v4)
  BEFORE touching Bao.
- Bao `secret/projects/pi-infinity-llm/KEEPER_TOKEN`: v1 (old) → v2
  (new). Old remains recoverable as Bao v1; server no longer accepts it
  (v5 smoke: 401). "Revoked" = rejected by every running alloc.
- Note: during the window the recorded public-host 403 had already cleared
  (Bao v1 token returned 200 on `keeper.pkubelka.cz/packs` at rehearsal
  start) — rotation proceeded anyway as cutover hygiene; v1-freeze origin
  is superseded by the Nomad deployment at hostname cutover.

## Follow-ups (not this goal)

- Hostname cutover to the Nomad deployment + tunnel/origin switch.
- Live Bao-export seeds (`SEED_FILE` via job template); rehearsal ran empty
  routes (smoke-compatible; packs carry no members until seeded).
- Consider Vault/Consul or Nomad workload identity so the bearer leaves
  job specs.
