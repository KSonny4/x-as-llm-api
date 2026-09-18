# L4 compliance report — x-as-llm-api + pi-infinity-llm (2026-09-18)

Point-in-time audit against L4 =
`engineering-guidance/standards/layer4-enforcement.md`
(§"What blocks a merge", §"Calibration path (normative)",
§"Owner override", §"Non-goals"). All gates were **informative** at audit
time: verdicts below record gaps as gaps. Nothing is backfilled (L4
forbids retroactive enforcement), no Owner cell is filled by machine.

Method: `git ls-tree` over `main` + lane branches, `gh pr view` 1–9
(2026-09-18), repo-wide grep for L4 markers, live suite runs, live
endpoint checks. Absence claims cite the exact command that returned empty.

## Scope correction

The goal statement says "4 open stacked PRs". Observed 2026-09-18:
**1 open** (`gh pr list --state open` → #9 only). PRs 1–8 merged
2026-09-18 13:19–17:32 UTC; the `pr1..pr4` lane branches persist locally
but are superseded. PRs 1–4 are judged from their bodies + branch tips;
PRs 5–8 from bodies + `main`; #9 live.

## Gate 1 — PR evidence receipt (pr-evidence/v1, revision == head, table in body)

**x-as-llm-api: GAP (partial history).**
- PRs 1–4 bodies carry renderer-formatted `pr-summary/v1` tables
  (`## Verification metrics` + `Generated from declared artefacts…`):
  PR1 receipt `9c3553672c…` == branch tip `9c3553672c…`
  (`git rev-parse pr1-matrix-dual-verify`); PR2 `04dbba49b9…` == head;
  PR3 `18c5255715…` == head; PR4 `e957e74076…` == head
  (`gh pr view N --json body,headRefOid`, 2026-09-18).
- BUT no receipt, artefact, or definitions file exists in any lane
  branch or `main`: `git ls-tree -r --name-only <branch> | grep -iE
  "evidence|receipt|artefact|calibrat|dimensions|l4/"` → empty on all
  four lane branches. Receipts lived outside the tree (PR bodies only);
  `definitions_sha` is unresolvable in-tree → not independently
  re-renderable. Recorded as gap, not reconstructed.
- PRs 5–9: no summary table in any body (`gh pr view`, `contains
  "Verification metrics"` false for 5–9).
- `main` history (`git log --oneline main`: `b4ce05a` cutover docs,
  `dba513c` seeds, `ec28bb1` loopback, …): no receipts → gap.

**pi-infinity-llm: GAP.** No PRs ever (`gh pr list --state all` →
empty); no receipt/artefact/definition files in `main`
(`36ae40a` strip, `162826d` values-mode, `592da97` helper sidecar).
`find . -iname "*evidence*"` → only this goal's new `docs/l4/`.

## Gate 2 — L3 dimensions table (human identity per row, incl. DDD/layout)

**GAP in both repos.** L3 requires one table beside the PR, columns
Dimension | Mark | Evidence | Held-by | Confidence
(`engineering-guidance/standards/layer3-ai.md:31`; DDD row without a
human identity is incomplete).
- No `Held-by`/dimensions table exists in either tree: repo-wide
  `grep -rliE "held-by|human verdict|dimensions table" --include="*.md"`
  → only this goal's new `docs/l4/policy.md` + `calibration.md`.
- PR bodies substitute decision tables (`Your checklist` PR1; `Decision
  for you` PR2–4, 9; same pattern PR6–8 per `has_owner_col`) whose
  **Owner cells are all empty** (`gh pr view 1/2/3/4/9`, 2026-09-18;
  e.g. PR1 `| Tests pass | receipt below … |  |`). No DDD/layout human
  mark exists anywhere.
- Machine-marking: PASS (vacuous) — nothing claims a human mark; empty
  cells were left empty, not filled.

## Gate 3 — Calibrated numeric thresholds

**INFORMATIVE (correct) in both repos.** No calibration record existed
before this goal (`find -iname "*calibrat*"` → empty, 2026-09-18), so
per L4 every numeric gate stays informative — which is the observed
state: nothing blocked, nothing auto-judged.
- Historical deviation (recorded, not re-judged): PR1–4 tables render
  `eq 0` thresholds with `measured / pass` verdicts
  (e.g. PR1 `keeper suite failures | 0 events | measured / pass | eq 0`)
  with no recorded calibration (tool versions, population, window,
  threshold choice, date, owner all absent). Under L4 those rows should
  have read Informational. Left as-is; future receipts use
  threshold-free definitions (`docs/l4/pr-metrics-definitions.json`
  carries no `threshold` keys → renderer emits `info`).

## Gate 4 — Owner override (receipted, never silent)

**NOT-APPLICABLE, no violation.** No gate was wired, so no red gate
existed to override; PRs 1–8 merged with empty Owner cells under the
informative migration L4 permits (`layer4-enforcement.md`: "existing
repos migrate gate by gate"). PR1 body states the rule explicitly
(`Do not merge past a red row without writing down why`). No merge
automation exists in-tree (`ls .github/workflows` → absent in both
repos); L4's no-auto-merge non-goal is satisfied by absence.

## Gate 5 — Never retroactive, never machine-marked (conduct of this audit)

**PASS.** History above is judged, not repaired: no backfilled
receipts, no filled Owner cells, no invented identities. New kit files
are additive only.

## Wired gates (this goal, additive)

x-as-llm-api `docs/l4/`: `policy.md` (gates + informative status +
calibration location), `pr-metrics-definitions.json` (`pr-metrics/v1`,
4 threshold-free metrics over `keeper-tests` + `probe-tests`),
`build-receipt.sh` (suites → `artefacts/*.json` → `receipt.json` →
guidance renderer `$EG_ROOT/tools/pr_evidence.py`), `calibration.md`
(all-informative + first-observation log). Pinning scheme: the trial
`receipt.json` / `summary.md` / `summary.json` cover HEAD~1 (the judged
code head) and are carried by HEAD (evidence-only delta), so the
receipted revision is exact and every re-run at any head exits 0 with
revision == that head (self-healing; renderer refusal exit 2 on
stale/tampered/missing).
pi-infinity-llm `docs/l4/`: same shape and pinning scheme; inputs `extension-tests`
(`node --test test/helper.test.js test/values.test.js`) +
`helper-tests` (`cargo test`); trial render exit 0, revision == the
judged head.
Renderer: `engineering-guidance/tools/pr_evidence.py` (`main` exits 2
on stale/tampered/missing; revision match enforced in `build_summary`).

## Suite evidence (2026-09-18 live runs)

- `python3 -m unittest discover -s keeper` → 108/108 OK.
- `python3 -m unittest discover -s probe` → 14/14 OK.
- `node --test test/helper.test.js test/values.test.js` (node v26.7.0)
  → 11/11 pass. (`node --test test/` alone fails: directory-as-module
  resolution; file paths required — recorded so the contract's
  `node --test` reads correctly.)
- `cargo test` (helper) → 10 passed, 0 failed.

## Keeper UI access

`docs/keeper-ui-access.md`: URL `https://keeper.pkubelka.cz`, bearer
auth, cookie-session browser path. Verified live 2026-09-18: bearer
`GET /api/v1/matrix` → 200 (1 email, 46 cols); `POST /api/v1/session`
→ cookie; cookie `GET /` + `GET /api/v1/matrix` → 200; cookie POST →
401; logout → cookie dead (401).

## OUT respected

No PR merged, no Owner cell filled, no Grafana import/contact change, no
image retag, no serving-behavior change, no backfilled receipts.
