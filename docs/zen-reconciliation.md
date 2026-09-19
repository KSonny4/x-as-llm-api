# Zen key reconciliation (M1) — 2026-09-19

Source: Bao `secret/projects/pi-infinity-llm/` metadata (status/email
fields only; values never read). Matrix: 8 owner rows × 66 cols live.

| Bao key | Status | Owner email | Verdict |
|---|---|---|---|
| OPENCODE_ZEN_API_KEY | active | ksonny4@gmail.com | LIVE (`zen/big-pickle-spare`) |
| OPENCODE_ZEN_API_KEY_PETR | active | petr1kubelka@gmail.com | LIVE (`zen/big-pickle`) |
| OPENCODE_ZEN_RETIRED_1 | expired-gateway, probe `dead:429` | jannovak12390@gmail.com | placeholder (never probed) |
| OPENCODE_ZEN_RETIRED_2 | expired-gateway, probe `dead:429` | petaazdenicka@gmail.com | placeholder |
| OPENCODE_ZEN_RETIRED_3 | expired-gateway, probe `dead:429` | friedmanbob2@gmail.com | placeholder |
| OPENCODE_ZEN_RETIRED_4 | expired-gateway, probe `dead:429` | zdenickaapeta@gmail.com | placeholder |
| OPENCODE_ZEN_RETIRED_5..8 | expired-gateway, probe `dead:429` | (unrecorded) | placeholder |

Retired keys are dead by their own metadata (gateway-expired after
429 throttling) — placeholders are honest, not gaps.

## Pending owner input (REQUIRED for M3)

Owner states more live Zen keys exist but has not named them. To seed:
reply with Bao key names (or where they live). Until then the confirmed
set is exactly the 2 live keys above; no reseed will be run (a no-change
redeploy would wipe in-memory probe states for nothing).
