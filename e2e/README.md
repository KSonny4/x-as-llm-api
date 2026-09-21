# e2e/ — deployed baselines (E2E-first evidence)

- `deployed-baseline.sh` — live curls against the keeper deployment. Gates all v2 code.
- `baseline-shapes.json` — member shapes with values redacted (models/providers only).

Baseline 2026-09-17 (`https://keeper.pkubelka.cz`): `/healthz` 200; `/packs`
no-bearer 401, garbage bearer 401, Bao-stored `KEEPER_TOKEN` **403** (OPEN —
reconcile/rotate with deploy owner). Origin unproven (retired-app deploy failed
on record; Cloudflare masks origin).
