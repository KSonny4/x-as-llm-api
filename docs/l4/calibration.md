# Calibration record — x-as-llm-api

Status: **informative on every gate**. No numeric threshold is enforced;
every metric renders `Informational` until a calibration below is recorded.

## How to calibrate a gate (L4 normative)

Record: tool versions, population, window, observed values, chosen
threshold, date, owner. Flip that gate — and only that gate — to
`enforcing`. Never flip all gates at once; never backdate enforcement
onto already-merged work.

## Gates

| Gate | Status | Calibration |
|---|---|---|
| PR evidence receipt (revision match + body table) | informative | none recorded |
| L3 dimensions table (human identity per row) | informative | none recorded |
| Numeric thresholds (suite pass counts) | informative | none recorded — first observation: keeper 108/108, probe 14/14 on 2026-09-18 (single run, not a population) |
| Owner override (receipted, never silent) | informative | none recorded |

## First-observation log (not calibration)

- 2026-09-18: keeper 108 passed / 108 total; probe 14 passed / 14 total
  (`python3 -m unittest discover -s keeper|probe`). One run = one data
  point; a threshold needs a population over a window.
