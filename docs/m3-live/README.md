# M3 live receipt — :main-a2ebb09, 5-route reseed (2026-09-18)

Proves the all-models matrix is live on merged `main` (PR #8, merge
`a2ebb09`). Each file is a captured artifact, re-verifiable as noted.

- `arch.txt` — `docker inspect`: `arch=amd64` + image digest.
- `alloc.txt` — Nomad `keeper` running alloc id + job version.
- `healthz.txt` — public `GET /healthz` → 200.
- `packs.json` — public `GET /packs` (credential values redacted to
  `{type, present}`): 5 packs, every `path: infinity/<provider>/<model>`,
  incl. `infinity/claude/claude-sonnet-4-6`.
- `matrix.txt` — public matrix: 1 email row, 5 routed columns with real
  states + `checked_at`, 46 total columns,
  `inventory_more: {openrouter: 424, gemini: 29}`.
- `metrics.txt` — 5 `keeper_route_divergent` series (all 0 here: no
  L1-fail+L2-pass split at capture time).
- `reseed.json` — the 5-route seed source (api_key values redacted to
  presence+length): rotated OpenRouter key (`_2`), unchanged zen,
  new gemini-3.6-flash (Google retired 2.5-flash for new users),
  kimi-k2.7-code, claude-sonnet-4-6 (documented Anthropic ID).
  The same content (with values, deploy-only) is passed via Nomad `-var`.
- `tripwire.log` — `keeper/tripwire.sh` output: CLEAN (script matches
  real key formats; short fixture stubs structurally excluded).

Notes: Gemini/Moonshot states vary run to run (depleted prepay / 429) —
both are honest provider-side states, not code faults. No UI screenshot
is attached: this environment has no image-input path, so visual proof
is unavailable rather than invented; the page HTML is asserted in tests
(legend, colors, Muse column, poller).
