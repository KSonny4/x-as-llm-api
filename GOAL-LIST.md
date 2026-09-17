# Big goal queue — full keeper rebuild (glla `/list`)

Paste each block with `/list` (one item per block). Items activate in order;
each is audited on its `Done when` before the next starts. Work in
`/Users/ksonny/git_projects/x-as-llm-api` unless noted.
E2E-first (EG rule 12): every item replays curls against the Nomad URL —
local-only green gates nothing.

## Item 1 — Repo live
```
/list Create GitHub repo KSonny4/x-as-llm-api from . and push main (gh repo create --public --source=. --push). Done when: gh repo view KSonny4/x-as-llm-api --json url prints the URL and git status is clean
```

## Item 2 — Smallest slice on Nomad
```
/list TDD: keeper/server.py GET /healthz -> 200 ok (stdlib only, KEEPER_TOKEN required, bearer on everything else), Dockerfile, compose.yaml (dev), keeper.nomad.hcl (prod, /healthz check), KEEPER_API.md stub, scripts/smoke.sh <url>. Deploy to Nomad and smoke the Nomad URL. Done when: bash scripts/smoke.sh $NOMAD_KEEPER_URL prints ok and python3 -m unittest passes in keeper/
```

## Item 3 — Values API on Nomad
```
/list TDD Tasks 3-6: GET /packs values wire (credential.value, ETag/304, max-age 600, SEED_FILE fixtures), POST /feedback (202 spool, 422 validation), GET /v1/providers + /v1/guide/:who emitting one OpenAI curl per model. Seeds export live Bao refs (exclude *_UNAVAILABLE/*_RETIRED/*_INACTIVE/*_BANNED). Redeploy + smoke Nomad URL. Done when: unauthed /packs -> 401, If-None-Match -> 304, bad feedback -> 422, and smoke.sh against Nomad URL is green
```

## Item 4 — OpenAI-out on Nomad
```
/list TDD Tasks 6b-6d: keeper/translate.py (openai<->anthropic both-ways, fixture tests: messages, tool_calls, usage, SSE chunks, errors), POST /v1/chat/completions (+streaming) + GET /v1/models + GET /v1/route/:model (200/401/404). Seed defaults Muse->openai, Alpha->anthropic; wire internal-only. Redeploy + smoke Nomad URL. Done when: stubbed openai + anthropic routes return identical OpenAI choices via chat/completions and test_translate passes
```

## Item 5 — Matrix UI on Nomad (deprecates llm-quota surface)
```
/list TDD Tasks 7-9: keeper/matrix.py (port llm-quota grouping: email dedupe, name-fallback, unassigned, skippedInactive) + Task 7b AA snapshot fetch (ARTIFICIALANALYSIS_API_KEY, tiebreak only, last-good retained) + GET /api/v1/matrix|accounts|health + server-rendered / /guides /signin /report (no framework, values never in HTML). Redeploy + smoke Nomad URL. Done when: ported matrix cases pass and / returns a table with diagnostics.unassigned on the Nomad URL
```

## Item 6 — Probes: L1 curl, L2 opencode CLI
```
/list TDD Tasks 10-11: probe/worker.py L1 (models 200 + ping chat; wire-aware; 429 -> limited+backoff, deny -> suspect+feedback, wrong-wire -> misconfigured) + L2 opencode run --pure on L1 fail (pass -> degraded, fail -> down) + status.json + compose/probe wiring. Done when: probe tests pass against stub baseURL + stubbed CLI and status.json contains ok/degraded/down transitions
```

## Item 7 — Extension repo minimal (in pi-infinity-llm checkout)
```
/list In ~/git_projects/pi-infinity-llm: branch archive/pre-split + push, then strip to extension-only from the pi-multi-providers tree (keep extension/, tests, minimal README -> KEEPER_API.md, AGENTS.md pin). Then values mode: served credential.value injects Authorization + x-api-key, signin members surface re-mint, CONNECTION_KEY_ENV deleted. Done when: node --test passes (values.test.js) and npx tsc --noEmit is clean
```

## Item 8 — Rust keeper-helper
```
/list In pi-infinity-llm/helper: cargo project with mint-zen-session (u64-exact vectors vs known-good), sign (credential JSON -> headers JSON), shape (probe/feedback normalize), stdin/stdout JSON, never log values; extension spawns it (in-TS mint deleted, headers fresh per request). Done when: cargo test passes and extension tests pass with helper-spawned headers
```

## Item 9 — Nomad cutover + deprecations
```
/list Rehearse rollback (Nomad revert forth/back, smoke both), rotate KEEPER_TOKEN to fix the recorded 403 (parallel-accept until smoke green), cut v2 to keeper.pkubelka.cz from Nomad, remove Coolify keeper app, write llm-quota DEPRECATED.md + archive. Done when: public curl https://keeper.pkubelka.cz/healthz -> 200, authed chat completion via hostname returns text, and smoke.sh against the hostname is green
```
