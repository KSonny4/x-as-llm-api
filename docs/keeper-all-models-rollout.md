# Keeper all-models rollout / rollback (parent-owned)

This is deployment preparation, not a deployment receipt. The worker neither
pushes images nor changes cluster state or secrets. Latest approved service API
amendment: `docs/plans/2026-09-20-keeper-service-amendment.md`.

## Required control before changing CLI integration

**Original zencli has a successful Nomad HTTP sanity check:** unchanged `main-1`,
`big-pickle`, HTTP **200**, answer `September 20, 2026.` The exact key also passed
the local CLI command. Preserve the original source/image and compare candidate
behavior against [this receipt and reproduction](zencli-sanity-check.md).

A direct Zen HTTP failure, a changed custom agent, or normal CLI stderr status
cannot invalidate that control. The successful control is not the modified
candidate and is not proof of public Keeper rollout. Keep these gates distinct.

## Verified infrastructure facts supplied by parent

- Live node: `ovh-nomad-fresh` (`d9619812-d1da-b474-2723-ffca768fb5be`).
- `driver.docker.volumes.enabled=true`; only named host volume is
  `registry-data`, **not** a Keeper volume. Use the supported Docker bind:
  `/opt/nomad-volumes/keeper:/var/lib/keeper` (parameter `keeper_data_path`).
- Old job v11 / allocation `115dda70` uses image `main-keyqueue10` and
  allocation-local `/alloc/probe.db`; only legacy `probe_detail` table.
- Parent has an integrity-checked predeploy backup; refresh immediately before
  rollout. Do not silently discard legacy history. Availability uses a separate
  `availability.db`, never imports ambiguous legacy success.
- Parent's local Nomad forward is `http://127.0.0.1:4647`; old public Nomad URL
  returns HTML. ACL comes from Bao `secret/projects/nomad/NOMAD_BOOTSTRAP`, field
  `acl_token`. Do not print the value or rendered job/seed responses.
- Public origin is `https://keeper.pkubelka.cz`. Dedicated non-expiring service
  bearer already provisioned by parent in Bao
  `secret/projects/pi-infinity-llm/KEEPER_SERVICE_TOKEN`, field `token`.

## Local checked build

From this worktree only:

```sh
(cd keeper && python3 -m pytest -q)
(cd probe && python3 -m pytest -q)
(cd scripts && python3 -m pytest -q)
node --check keeper/dashboard.js
nomad fmt -check keeper.nomad.hcl
docker build --platform linux/amd64 --build-arg BUILD_ID="$(git rev-parse HEAD)" -t keeper:all-models-check keeper
```

The image copies every runtime module/static asset, and checks imports/assets
at build time. Live node is linux/amd64: inspect the final image Architecture,
never publish an accidental Mac arm64 build. Production startup requires an explicit absolute
`AVAILABILITY_DB` and HTTPS `PUBLIC_ORIGIN`; no allocation-local default.
`BUILD_ID` is returned only in authenticated catalog. Resources remain unchanged
(200 MHz / 128 MiB); do not increase without live measured need.

## Parent rollout order

1. Freeze reviewed commit and obtain fresh independent correctness/security
   review. Build/publish the exact commit image with immutable tag/digest;
   inject registry auth in memory or mode-0600 temporary files, never logs.
2. Refresh the old database backup using SQLite backup API (including WAL),
   integrity-check it, record non-secret size/table counts. Keep backup outside
   both old allocation and target directory. Export no provider values.
3. Provision dedicated node directory `/opt/nomad-volumes/keeper` mode 0700,
   owner matching image runtime UID (currently root). Copy the legacy DB to
   `/opt/nomad-volumes/keeper/probe.db` only if absent; never overwrite a newer
   file. Preserve existing availability DB and WAL if present. Take a SQLite
   backup before any schema upgrade. Do not mount registry-data or allocation
   directories as purported durable storage.
4. Supply `keeper_image`, `keeper_data_path`, `public_origin`, administrator
   token(s), **separate** `keeper_service_token`, AA key, registry auth and
   current rendered seed JSON via private input. Startup rejects service/admin
   token equality. Preserve credential generation metadata from render-seeds.
5. Validate/plan the job using the real Nomad connection; inspect only redacted
   plan summaries. Stop redundant legacy periodic probes, or at least ensure
   they cannot create v2 proof (v2 deliberately ignores their evidence).
6. Deploy only Keeper. Its single daemon worker refreshes discovery/AA and
   schedules full eligible Cartesian coverage once per durable 24h window.
   Polling is local SQLite only. Background failure is exposed in catalog;
   don't call a failed worker healthy merely because `/healthz` answers.
7. Run `/srv/keeper/smoke.py` inside the allocation. Default is read-only:
   private dashboard/catalog auth, no-store, isolation, worker health. Optional
   `SMOKE_CHECKS=1` queues a paced complete sweep, `SMOKE_INFERENCE=1` exercises
   the service alias, `SMOKE_MODEL_ID=<exact catalog id>` checks credential
   retrieval without printing it. Never enable fixture feedback in production.
8. Use a redacting parent process to retrieve one actual provider credential
   and make a direct inference request to the advertised endpoint with its
   exact model/protocol/headers. Keep keys in memory; don't save HTTP traces,
   screenshots of secret panels, responses, environment dumps, or shell history.
   Verify alias nonstream, streaming and tools with the service bearer too.
9. Record total keys/models/pairs, eligible/blocked/pending/cooldown counts,
   observed successes/failures and build ID, without key values. Require honest
   unknown/free-tier-unverified states; do not pay to obtain green coverage.
10. Prove durability: record selected non-secret observation/job/history counts,
    replace the allocation, and show the same DB evidence/cooldowns survives.
    Node-local bind survives allocation replacement on that node, **not node
    loss**. Back it up off-node; constrain/migrate storage before multi-node
    scheduling. Current cluster fact is one live Keeper node; don't invent HA.

## Rollback

Keep prior job/image and predeploy DB backups. Stop new worker before restoring
anything. Roll back image/job without deleting the host directory. Old Keeper
can use preserved `probe.db`; it does not understand the new availability
schema. Restore a backup only when needed, offline, keeping the failed copy for
forensics. Never roll back a credential generation or resurrect revoked keys.
Service-token consumers require the new service API; old image has no such
principal. Report this interruption explicitly. Rotate secrets only if exposure
is suspected, using the existing Bao source of truth.

## Known compatibility boundaries

Legacy raw `/packs` and `/v1/route/*` are unverified, administrator-bearer-only,
no-store. New browser/API selection uses only exact observations. Legacy matrix
shape is preserved in the candidate, but its columns have exact route IDs and
v2 transport-scoped evidence: CLI is L2, never direct/L1 proof. Unmatched AA IDs stay unscored; a stale cached Coding
Index is labelled as such. Protocol feature limitations are in `KEEPER_API.md`.

## Approved genuine-CLI sidecar integration (latest topology)

The user explicitly required reuse of the repository's proven genuine OpenCode
bridge as a distinct service backend; direct HTTP rejection must not erase that
option. New root README and engineering guidance describe its text-only limits.
Historical main-1 proof is not a hardened-image live receipt.
The [2026-09-20 private staging run](keeper-staging-2026-09-20.md) is stopped:
hardened CLI inference was rejected and direct checks were rate-limited;
production was not switched.

Parent's isolated preflight proved CNI bridge **unavailable** (missing
`${attr.plugins.cni.version.bridge}`), then proved Docker `network_mode=host`
shared loopback with two tasks; allocation `e81d43b1-a586-0131-6ec5-12a1a9f79743`
completed with neither task failed. The preflight job was stopped; no provider
calls were involved. Do not install host CNI as part of this rollout.

Latest controlled parent comparison isolates CLI host-network egress failure for
the tested key/model/input. The current job retains Keeper host-loopback 8102 but
moves CLI to Docker bridge with authenticated HTTP over private Unix socket
`/alloc/data/keeper-zencli/http.sock`. No internal TCP reservation/publication,
CNI or node-wide changes. See [latest topology/security/migration gate](keeper-uds-clock-repair.md).
The fixed node/durable Keeper bind and destructive static-8102 update remain;
account for the short interruption. Earlier shared-loopback preflight above
proved connectivity only, not suitability for genuine CLI upstream egress.

Supply new required `zencli_image` and `keeper_zencli_token` variables. Parent's
internal bearer source is Bao
`secret/projects/pi-infinity-llm/KEEPER_ZENCLI_TOKEN`, field `token`.
It must differ from both admin and public service tokens; startup checks this.
Only Keeper + sidecar receive it. The sidecar receives no seed/admin/service
secret, host DB or auth-volume mount; Keeper sends one selected key per private
request. Ephemeral catalog/auth are rebuilt, not treated as durable evidence.

Build and inspect **both** images as linux/amd64:

```sh
docker build --platform linux/amd64 --build-arg BUILD_ID="$(git rev-parse HEAD)" \
  -f zencli/Dockerfile -t keeper-zencli:all-models-check .
docker image inspect --format '{{.Architecture}}' keeper-zencli:all-models-check
```

Sidecar uses 1024 MiB / 500 MHz based on the existing measured Nomad proof
(256 MiB caused SIGKILL); node capacity was verified by parent. Keeper remains
128 MiB / 200 MHz. Test readonly-rootfs/tmpfs/no-new-privileges/cap-drop settings
with the actual pinned CLI before rollout; don't assume build-only proof is enough.
CLI inference has a 110s deadline and Keeper's internal request timeout is 120s;
long requests may also encounter external tunnel timeout. No user quota/cap is
introduced. Native tool definitions remain; permission requests are auto-rejected except
exact native clock execution through the immutable no-shell gate (no custom
agent or step limit). Streaming/tools require a compatible direct
backend and must not be silently downgraded.

The complete matrix now contains separate direct and CLI routes. Require actual
postdeploy CLI receipts with exact selected key/model and separate direct-route
results; do not count old CLI records as new checks. Parent must run a minimal
plain-text alias request **without generation controls** for bridge eligibility.
Never activate the historical default-auth `zencli/entry.sh` in this service job.


## Latest native CLI / transport repair

Follow [exact-key canary and schema-2 migration/rollback](keeper-transport-repair.md)
for the replacement candidate. Direct free Zen inference checks are now blocked
by explicit `cli_required` policy, not needed as a prerequisite for CLI checks.
Only actual new exact CLI evidence counts; do not import the protected receipt.
Rollback to schema-1 code requires the pre-upgrade availability DB backup.


Current candidate requires schema 3. Preserve pre-upgrade DB backup for rollback;
only evidenced active prior CLI limits carry to UDS, explicitly attributed and
never as success. Parent must return the same-question live canary result before
writer readiness or final review. The single-variable evidence does not justify
changing noexec/nonroot protections or ignoring real provider limits.
