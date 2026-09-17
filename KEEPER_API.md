# KEEPER_API — v2 draft (`keeperPackVersion: v2-skeleton`)

One-way contract: pi-infinity-llm pins this; keeper never imports from it.
Changes are additive + version-bumped.

| Method & path | Auth | Status |
|---|---|---|
| `GET /healthz` | none | live → `ok` |
| everything else | `Bearer $KEEPER_TOKEN` (401 otherwise) | 404 until later lanes land |

Planned (later lanes, additive): `GET /packs`, `POST /feedback`,
`GET /v1/providers`, `GET /v1/guide/:who`, `POST /v1/chat/completions`,
`GET /v1/models`, `GET /v1/route/:model`, `GET /api/v1/matrix|accounts|health`, `/`.
