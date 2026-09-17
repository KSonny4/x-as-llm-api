# x-as-llm-api — Keeper + opencode-as-API + curl-as-API

> Status: **PLAN** (nothing built yet, repo is empty except `.pi-glla/`).
> Goal: one `docker compose up` that gives anyone on the team: **working tokens/credentials,
> copy-paste curls, and ready pi / opencode configs** — plus **auto validation + a feedback
> channel** when something stops working.

---

## 1. What you asked (in my words)

- A **keeper/dispenser**: holds the *good* API keys, validates them, and hands out
  *whatever one needs to do a request* (raw key, baseURL, model id, headers, snippet).
- **opencode as API**: wrap the painful `opencode serve` REST flow behind 1–2 simple calls.
- **curl as API**: every capability must be doable + documented as a plain `curl`.
- **Consumers = everyone**: humans with curl, `pi` agents, `opencode` agents/SDKs.
- **Health + feedback**: automatic checks (green/red per provider) + a `/report` endpoint
  where users flag "this key / model is broken".
- **Dockerized full stack**: `keeper + opencode + docs` in one compose file, keys via `.env`.

## 2. What exists on this machine today (inventory, 2026-09-17)

| Thing | Found |
|---|---|
| `pi` auth providers (`~/.pi/agent/auth.json`) | `opencode-go`, `opencode`, `meta`, `openai-codex` (OAuth), `omniroute`, `zai`, `groq`, `openai`, `openrouter` (api keys) |
| `opencode` credentials (`~/.local/share/opencode/auth.json`) | `DeepSeek`, `Nvidia`, `OpenCode Zen`, `OpenCode Go` |
| `opencode.jsonc` custom provider | `omniroute` → `http://127.0.0.1:20128/v1` with `OMNIROUTE_API_KEY`, models `opencode-muse`, `muse`, `implement-1m`, `zen` |
| `opencode serve` API | live-probed on `:40999`: OpenAPI at `GET /doc`, **~100 paths** (`/session`, `/session/{id}/message`, `/session/{id}/prompt_async`, `/event` SSE, `/provider`, `/config`, …). No auth by default (warns `OPENCODE_SERVER_PASSWORD is not set`). `GET /session` and `GET /provider` work unauthenticated. |
| Docker | `Docker version 29.8.0` available |
| Repo `x-as-llm-api` | empty — greenfield |

### Why "opencode requests are difficult" — confirmed

Raw flow to get one answer today:

```bash
# 1. serve (needs password + CORS in prod)
opencode serve --port 4096 --hostname 127.0.0.1 &

# 2. create session
curl -X POST http://127.0.0.1:4096/session \
  -H 'Content-Type: application/json' -d '{"title":"test"}'
# → {"id":"ses_xxx", ...}

# 3. prompt (must know providerID/modelID/agent, response is SSE-ish parts)
curl -X POST http://127.0.0.1:4096/session/ses_xxx/message \
  -H 'Content-Type: application/json' \
  -d '{"parts":[{"type":"text","text":"hi"}],"model":{"providerID":"opencode","modelID":"big-pickle"}}'

# 4. stream/follow events via /event or /session/{id}/message — non-trivial in bash
```

Plus discovery pain: model ids differ per provider (`providerID/modelID` pair),
auth is per-provider (`PUT /auth/{providerID}`), errors are `effect_HttpApiError`
shapes. **The keeper must hide steps 2–4 behind one call.**

---

## 3. Architecture (target)

```
                    ┌─────────────────────────────────────────┐
                    │           docker compose stack          │
                    │                                         │
  teammate ──curl──▶│  keeper :8787                           │
  pi ──────────────▶│   ├ GET  /v1/status        (green/red)  │──▶ health checker (in-process cron)
  opencode ────────▶│   ├ GET  /v1/providers     (what works) │──▶ status.json
                    │   ├ GET  /v1/guide/:who    (curl/pi/    │──▶ probes each key:
                    │   │      opencode snippets)             │    GET /v1/models + tiny chat
                    │   ├ POST /v1/chat          (1-call LLM) │
                    │   ├ POST /v1/opencode/run  (simplified  │──▶ opencode :4096
                    │   │      session+prompt+wait)           │    (serve --hostname 0.0.0.0,
                    │   └ POST /v1/report         (broken!)   │     OPENCODE_SERVER_PASSWORD,
                    │                            ▲            │     shared auth volume)
                    │   docs :5173 (Vite static: paths,      │
                    │   guides, status dashboard, feedback    │
                    │   form → POST /v1/report)               │
                    └─────────────────────────────────────────┘
  Secrets: only in `.env` (never committed). Keeper never prints
  raw keys to logs; /v1/providers returns keys ONLY with a
  bearer token (team token), otherwise returns redacted + instructions.
```

**Service list (compose):**

| Service | Image | Ports | Notes |
|---|---|---|---|
| `keeper` | build `./keeper` (node:22-slim, tiny express/hono app) | `8787:8787` | simplified API + validation cron + serves `public/` fallback |
| `opencode` | build `./opencode` (`node:22-bookworm` + opencode binary, or `sst/opencode` image if pinned) | `4096:4096` | `serve --port 4096 --hostname 0.0.0.0`, `OPENCODE_SERVER_PASSWORD` from `.env`, volume `opencode-auth:/home/opencode/.local/share/opencode`, read-only mount of team `opencode.jsonc` |
| `docs` | build `./docs` (vite build → nginx, or `vite preview`) | `5173:80` | status dashboard + per-consumer guides + feedback form; optional in MVP (keeper can serve static first) |

## 4. Keeper API contract (the "dispenser of whatever one needs")

All JSON. Auth: `Authorization: Bearer $KEEPER_TEAM_TOKEN` required for any
response containing a raw key; without it, keys are `sk-…<redacted>` + instructions.

| Method & path | Purpose | Example |
|---|---|---|
| `GET /health` | liveness | `{"ok":true}` |
| `GET /v1/status` | per-provider/key health: `ok/degraded/down`, latency, last check, model count | consumed by docs dashboard |
| `GET /v1/providers` | **the dispenser**: for each working provider → `providerID`, `baseURL`, `modelIDs[]`, `envVar`, `apiKey` (if authed), `curl` snippet, `pi` snippet, `opencode` snippet | single source of truth |
| `GET /v1/guide/curl` | copy-paste curls for chat + models + opencode-run | onboarding |
| `GET /v1/guide/pi` | what to inject in `pi`: env exports, `--provider/--model`, `pi auth check` command | onboarding |
| `GET /v1/guide/opencode` | `opencode.jsonc` provider block + `PUT /auth/{id}` curl + `opencode run --model` | onboarding |
| `POST /v1/chat` | **1-call LLM** (hides opencode dance): `{provider, model, prompt, system?}` → `{text, model, usageMs}`. Implemented as: create session → post message → poll/wait → return text. Fallback: direct OpenAI-compatible `POST {baseURL}/chat/completions` when provider supports it | `curl -X POST keeper:8787/v1/chat …` |
| `POST /v1/opencode/run` | escape hatch to full opencode: `{message, model?, agent?}` → waits for completion, returns final parts | for agentic tasks |
| `POST /v1/report` | **feedback**: `{provider, model?, what, contact?}` → marks key `suspect`, triggers immediate re-check, appears on dashboard | "smth does not work" button |
| `POST /v1/refresh` | force re-validation now (team token) | after rotating a key |

### Consumer snippets the keeper must emit (exact strings, tested in CI)

**curl (OpenAI-compatible provider, e.g. omniroute):**
```bash
curl -s http://keeper:8787/v1/chat \
  -H "Authorization: Bearer $KEEPER_TEAM_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"provider":"omniroute","model":"muse","prompt":"say hi"}'
```

**pi:**
```bash
export OMNIROUTE_API_KEY="$(curl -s http://keeper:8787/v1/providers \
  -H "Authorization: Bearer $KEEPER_TEAM_TOKEN" | jq -r '.omniroute.apiKey')"
pi --provider omniroute --model omniroute/muse -p "say hi"
# check: pi auth check --provider omniroute
```

**opencode (config + run):**
```jsonc
// paste from GET /v1/guide/opencode into opencode.jsonc
{ "provider": { "omniroute": {
  "npm": "@ai-sdk/openai-compatible",
  "options": { "baseURL": "http://keeper:8787/proxy/omniroute/v1",
               "apiKey": "{env:OMNIROUTE_API_KEY}" } } } }
```
```bash
opencode run -m omniroute/muse "say hi"
```

## 5. Validation + feedback design

- **Checker** (inside keeper, `setInterval`, default 5 min + on `POST /v1/refresh` + on `POST /v1/report`):
  1. `GET {baseURL}/models` with key → must be 200 + non-empty list.
  2. Tiny chat probe (`max_tokens: 8`, prompt `ping`) → must return text.
  3. For opencode-native providers: `GET opencode:4096/provider` + `POST /session` + tiny `/message`, then delete session.
  4. Write `status.json` `{provider: {state, latencyMs, lastOk, lastError, models}}`; serve via `GET /v1/status`.
- **Feedback**: `POST /v1/report` → sets `suspect=true`, immediate re-probe; if probe fails → `down` + dashboard red + log line; if probe passes → `flaky` note ("works for robot, check your snippet version").
- **Rotation**: keys only via `.env` / compose secrets; `POST /v1/refresh` re-reads env (or restart). Document rotation runbook in docs UI.

## 6. Docs (Vite) — "paths and guidance"

- Pages: `/` (status dashboard from `GET /v1/status`), `/curl`, `/pi`, `/opencode`, `/report` (feedback form).
- Each guide page renders **live snippets** fetched from keeper (`/v1/guide/:who`) so docs never go stale; with copy buttons.
- MVP shortcut: keeper serves `public/index.html` static; split to real Vite app in Phase 3.

## 7. Repo layout to create

```
x-as-llm-api/
├── docker-compose.yml        # keeper + opencode + docs, .env driven
├── .env.example              # KEEPER_TEAM_TOKEN, OPENCODE_SERVER_PASSWORD, *_API_KEY=…
├── keeper/
│   ├── Dockerfile
│   ├── package.json          # express (or hono) + node-fetch; no DB
│   ├── src/index.js          # routes above + checker cron
│   └── public/               # fallback static docs (before Vite split)
├── opencode/
│   ├── Dockerfile            # installs opencode, runs serve
│   └── opencode.jsonc        # team base config (omniroute etc., no secrets)
├── docs/                     # Vite app (Phase 3)
│   └── src/…
├── scripts/
│   ├── check-keys.sh         # manual pre-docker validation (curl probes)
│   └── smoke.sh              # post-up: /health → /v1/status → /v1/chat → /report
└── PLAN.md (this file)
```

## 8. Build phases (small, verifiable)

- [ ] **P0 skeleton** — compose file, `.env.example`, keeper `GET /health`, `opencode serve` container boots, `smoke.sh` green.
- [ ] **P1 dispenser MVP** — `GET /v1/providers`, `/v1/guide/:who` backed by env + static model lists; redaction without bearer token; tested curls in README.
- [ ] **P2 one-call facade** — `POST /v1/chat` + `POST /v1/opencode/run` against containerized opencode (session→message→wait inside keeper); `smoke.sh` asserts real text answer.
- [ ] **P3 validation + feedback** — checker cron, `GET /v1/status`, `POST /v1/report`, `POST /v1/refresh`, dashboard shows green/red.
- [ ] **P4 Vite docs** — split `docs/`, live snippets, feedback form, copy buttons.
- [ ] **P5 hardening** — `OPENCODE_SERVER_PASSWORD` + keeper team token enforced, CORS list, rate limit `/v1/chat`, no raw keys in logs, secret rotation runbook, pin opencode image version.

## 9. Decisions locked from your answers

1. Keeper = **dispenser of whatever a request needs** with emphasis on **de-trivializing opencode** → hence `POST /v1/chat` + `/v1/opencode/run` facade (Q1).
2. Consumers = **everyone** → three first-class guides: curl, pi, opencode (Q2).
3. Health = **auto checks + user reports** → cron + `/v1/report` → suspect/re-probe flow (Q3).
4. Scope = **full compose stack** (keeper + opencode + docs) (Q4).

## 10. What I need from you to start building (P0)

1. Which keys may I bake into the team's `.env`? (I see 9 pi providers + 4 opencode creds + omniroute — confirm which are shareable vs. personal OAuth like `openai-codex`/`meta` that can't go in docker.)
2. Team token strategy: single shared `KEEPER_TEAM_TOKEN` ok for MVP, or per-user tokens?
3. Which provider/model should be the default for `POST /v1/chat` when caller omits it? (suggest `omniroute/muse` since it's already configured).
4. Say the word and I start with **P0 skeleton** in this repo.

---
*Probed 2026-09-17: `opencode --version 1.18.31`, `pi 0.85.0`, `Docker 29.8.0`, OpenAPI `GET /doc` lists ~100 paths; full spec saved from local probe if needed.*
