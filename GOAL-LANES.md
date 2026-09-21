# Parallel lanes — full rebuild in 3 waves (glla-compatible)

Sequential `/list` finishes last. This runs independent lanes concurrently
(subagents or parallel sessions), merges, then cuts over. One writer per
worktree; lanes never share files.

## Wave 1 — 6 parallel lanes (start all at once, from docs only)

| Lane | Where | Files (exclusive) | Done when |
|---|---|---|---|
| L1 infra | x-as-llm-api `wt/infra` | `keeper/server.py` (healthz+auth skeleton), `keeper/Dockerfile`, `compose.yaml`, `keeper.nomad.hcl`, `KEEPER_API.md`, `scripts/smoke.sh`, `e2e/` | `smoke.sh <NOMAD_URL>` → ok |
| L2 translator | x-as-llm-api `wt/translate` | `keeper/translate.py`, `keeper/test_translate.py` | `python3 -m unittest test_translate` PASS (fixtures: messages, tool_calls, usage, SSE, errors) |
| L3 matrix+AA | x-as-llm-api `wt/matrix` | `keeper/matrix.py`, `keeper/test_matrix.py`, AA fetch + cache | ported llm-quota grouping cases PASS; fixture AA → scores; failure → last-good |
| L4 probes | x-as-llm-api `wt/probe` | `probe/worker.py`, `probe/test_worker.py` | PASS vs stub baseURL + stub CLI; states ok/degraded/down/suspect/limited/misconfigured proven |
| L5 rust helper | pi-infinity-llm `helper/` | `helper/Cargo.toml`, `helper/src/main.rs` | `cargo test` PASS (u64 mint vectors, sign, shape; never log values) |
| L6 extension | pi-infinity-llm (pi-infinity-llm tree) | strip (archive/pre-split first) + `extension/` values mode + helper spawn | `node --test` PASS, `tsc --noEmit` clean, no `CONNECTION_KEY_ENV` |

Lane contract (read before starting): `docs/plans/2026-09-17-keeper-rebuild-design.md`
(§2 wire/translation, §3 matrix, §4+helper, §5 states) + `GOAL-LIST.md` item text.
No lane imports another lane's code — only the contract.

## Wave 2 — integrate (keeper repo, sequential, 1 writer)

Merge L1→main, then L2/L3/L4 on top (all additive). Wire Tasks 6/6c/6d/8/9
into `server.py`; guides pages; redeploy Nomad; replay full `smoke.sh`
+ e2e baseline against the Nomad URL. Done when:paro matrix green on the
Nomad URL + identical OpenAI `choices` from stubbed openai/anthropic routes.

## Wave 3 — cutover (1 writer + owner dashboards)

Rotate `KEEPER_TOKEN` (fix 403, parallel-accept first), cut hostname to Nomad
job, remove retired keeper app, `llm-quota/DEPRECATED.md` + archive.
Done when: public `curl https://keeper.pkubelka.cz/healthz` → 200,
authed chat completion returns text, hostname smoke green.

## Dispatch (subagents, one call)

```js
// one top-level call, async:true; one writer per worktree
await runs.lanes([
  {key:'L1', stages:[{key:'w', agent:'worker', task:'Wave1 L1 in wt/infra per GOAL-LANES.md'}]},
  {key:'L2', stages:[{key:'w', agent:'worker', task:'Wave1 L2 in wt/translate per GOAL-LANES.md'}]},
  {key:'L3', stages:[{key:'w', agent:'worker', task:'Wave1 L3 in wt/matrix per GOAL-LANES.md'}]},
  {key:'L4', stages:[{key:'w', agent:'worker', task:'Wave1 L4 in wt/probe per GOAL-LANES.md'}]},
  {key:'L5', stages:[{key:'w', agent:'worker', task:'Wave1 L5 in pi-infinity-llm/helper per GOAL-LANES.md'}]},
  {key:'L6', stages:[{key:'w', agent:'worker', task:'Wave1 L6 extension per GOAL-LANES.md'}]},
]);
// Wave 2+3 run after all lanes report success; reviewer gates each merge.
```

## glla mapping (locked: audit at merge)

Wave 1 lanes run as pure execution (no goal ledger/auditor — speed where safe).
Rigor lands at the merge gates and after:

- Each lane output gets a **reviewer pass** at merge (diff vs lane contract +
  lane Done-when; findings must clear before merging to main).
- **Wave 2 + Wave 3 run as glla `/list` items** (`GOAL-LIST.md` items 2–9,
  rebased onto merged main) with full loop machinery: ledger, isolated
  auditor with `<evidence>` per `Done when`, stall/error guards.
- `/list` queue stays the audit trail: mark items complete as their merge
  + audit finish. Lanes map: L1→items 1–2, L2–L4→items 3–6, L5ext→items 7–8,
  cutover→item 9.
