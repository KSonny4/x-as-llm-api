# Post-merge live loop on main-built images (2026-09-18)

All of PR1–PR4 is in `main` (@e8b8676 via PR #5). This record proves the
cluster now runs images built from merged `main`, and the full
dispatch → matrix → metrics → smoke loop is green on them.

## Images (linux/amd64, built from main tree, app bytes identical to pr4-*)

- `registry.pkubelka.cz/keeper:main-e8b8676`
  `@sha256:be5a949357ab9528543045549ea29f0258a3bc976273e4548e97eb3c47c71ef5`
- `registry.pkubelka.cz/keeper-probe:main-e8b8676`
  `@sha256:0798fd420a73d8960fa34600a6a3601f43eed87d2600bacb968880148feb1cf4`

Equivalence proof: `/srv/keeper` and `/srv/probe` extracted from
`pr4-3`/`pr4-2` vs the new images → `diff -r` clean on both.

## Deployments

- `keeper` service alloc `b7574453` on `:main-e8b8676`, `healthz 200`.
- `keeper-probe` batch re-registered on `:main-e8b8676` (same vars/seeds).

## Live loop evidence

- Dispatch `keeper-probe/dispatch-1789744127`, alloc `8a5fd235` (complete):
  `openrouter/openai/gpt-4o-mini -> ok (l1=ok) posted 202`;
  `opencode-zen/big-pickle -> degraded (l1=suspect) posted 202`;
  `2 reported, 0 failed`.
- `/metrics`: `keeper_route_divergent{...zen/big-pickle...} 1`,
  `openrouter/gpt-4o-mini 0`, both with fresh `keeper_probe_checked_at_seconds`.
- In-alloc smoke on probe image (alloc `7258416c`,
  `BASE=http://127.0.0.1:8102` since keeper listens on :8102 there):
  `SMOKE GREEN`.

## Incident during this rollout (honest record)

The first `:main-e8b8676` build was accidentally **arm64** (Mac default,
no `--platform`), which crash-looped on the amd64 node: ~25 min of HTTP 502
on the public hostname. Rolled back to `pr4-3` (byte-identical app code,
service `200` again within a minute), rebuilt with
`--platform linux/amd64`, re-verified arch + app bytes, redeployed.
Lesson: always `docker inspect --format {{.Architecture}}` before pushing
a tag the cluster pulls; consider an arch assertion in the build step.
