# M3 live receipt — :main-91c7cb8, 5-route reseed (2026-09-18)

Proves the all-models matrix is live on `main` (fix: `GET /packs` serves
the live inventory, not just seed routes). Each file is a captured
artifact, re-verifiable as noted.

- `arch.txt` — `docker inspect`: `arch=amd64` + image digest.
- `alloc.txt` — Nomad `keeper` running alloc id + job version.
- `healthz.txt` — public `GET /healthz` → 200.
- `packs.json` — public `GET /packs` (credential values redacted to
  `{type, present}`): 500 packs, every `path: infinity/<provider>/<model>`
  — 5 seeded routes with credentials/signin as before, plus 495
  inventory-only signin packs (openrouter 445, gemini 49, moonshot 1),
  incl. `infinity/claude/claude-sonnet-4-6`. The full enumerated list is
  in packs (uncapped); the matrix caps display columns at 20/provider
  with overflow in `diagnostics.inventory_more`.
- `matrix.txt` — public matrix: 1 email row, 5 routed columns with real
  states + `l1`/`l2` + `checked_at` (fresh `keeper-probe` dispatch at
  capture time), 46 total columns,
  `inventory_more: {openrouter: 425, gemini: 29}`.
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
both are honest provider-side states, not code faults. Probe detail
(`l1`/`l2`/`checked_at`) is in-memory server state: a redeploy resets
cells to unknown until the next `keeper-probe` dispatch; that is why
`matrix.txt` is captured right after a dispatch. No UI screenshot
is attached: this environment has no image-input path, so visual proof
is unavailable rather than invented; the page HTML is asserted in tests
(legend, colors, Muse column, poller).

## Addendum 2026-09-18 — 33-key reseed (job v20, images :main-76660e7)

All 33 `secret/projects/pi-multi-providers/` keys seeded via
`scripts/render-seeds.sh` (values Bao→`/tmp` only, never git): 11 live
routes with credentials (openrouter ×4, zen ×2, gemini, moonshot, claude
OAuth ×3 — same-model spares share columns, each keeps its own verdict
via per-`connection_id` probe ingest) + 22 keyless placeholders
(`wire: none`, never probed, honestly `unknown`): kilocode, cloudflare
×3, devin, codex, antigravity ×2, 2 inactive foreign keys, 8 retired
zen, 2 banned github, cursor + opencode-go unavailable. Owners come from
Bao `email` metadata (8 distinct rows; empty → operator fallback,
documented per route). `reseed-33.json` holds the redacted shape.
`packs.json` now 528 packs (11 credential + 517 signin); `matrix.txt` 8
emails × 66 columns, 11 live cells with `checked_at`, 22 placeholders
`unknown` without `checked_at` (never probed — by design, not by gap).
Zen `l2_ref: opencode/big-pickle` preserved on both live zen routes.
