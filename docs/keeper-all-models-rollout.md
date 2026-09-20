# Keeper all-models rollout / rollback (parent-owned)

This is deployment preparation, not a deployment receipt. The worker neither
pushes images nor changes cluster state or secrets. Latest approved service API
amendment: `docs/plans/2026-09-20-keeper-service-amendment.md`.

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
shape is preserved in production but its columns now have exact route IDs and
only v2 direct evidence. Unmatched AA IDs stay unscored; a stale cached Coding
Index is labelled as such. Protocol feature limitations are in `KEEPER_API.md`.
