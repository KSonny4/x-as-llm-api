# L4 policy — x-as-llm-api

L4 = `engineering-guidance/standards/layer4-enforcement.md`
(pinned where referenced; this repo does not vendor it).
L4 gates **presence of evidence**, never the content of a judgment.

## Gates (all INFORMATIVE until calibrated — see `calibration.md`)

1. **PR evidence receipt**: a valid `pr-evidence/v1` receipt whose
   revision matches the PR head, plus the rendered `pr-summary/v1`
   table in the PR body. Renderer refusal (exit 2) = gate red.
2. **L3 dimensions table**: present beside the PR with a human identity
   on every row, including DDD/layout
   (`engineering-guidance/standards/layer3-ai.md`). A missing identity
   = gate red; the machine never marks.
3. **Calibrated numeric thresholds**: block only after this project
   records a calibration. Uncalibrated = informative by definition.
4. **Owner override**: the owner may merge past a red gate only with a
   recorded reason beside the PR (same table, extra row). Silent merges
   past red gates are forbidden absolutely.
5. **Never retroactive, never machine-marked**: merged history keeps its
   pins and evidence; history gaps are recorded as gaps, never backfilled;
   no bot supplies a human mark.

## Status

Informative on every gate. No gate blocks merges today. Calibration
record: `docs/l4/calibration.md` (this file's location is the
calibration location).

## Tooling

- Definitions: `docs/l4/pr-metrics-definitions.json` (`pr-metrics/v1`).
- Build: `docs/l4/build-receipt.sh` — runs the hermetic suites, writes
  artefacts + `pr-evidence/v1` receipt, renders via the guidance
  renderer (`$EG_ROOT/tools/pr_evidence.py`, default
  `../engineering-guidance`). It executes nothing from definition files.
- Outputs (committed as trial evidence, stale on next commit by design):
  `docs/l4/artefacts/*.json`, `docs/l4/receipt.json`,
  `docs/l4/summary.md`, `docs/l4/summary.json`.
- Compliance report (point-in-time audit, not a gate):
  `docs/l4/compliance-report.md`.
