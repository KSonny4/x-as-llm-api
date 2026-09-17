# Keeper Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the keeper in `KSonny4/x-as-llm-api` (values API, guides, matrix UI, probes) and strip `KSonny4/pi-infinity-llm` to the v2 extension + Rust helper, then cut over and deprecate `llm-quota`.

**Architecture:** Python stdlib-only keeper service (zero deps); prod deploys as a Nomad job (`keeper.nomad.hcl`, secrets from Bao), local dev via Compose; probe worker as second task of the same job; TS extension + Rust `keeper-helper` sidecar in the extension repo; one-way contract via `KEEPER_API.md` + `keeperPackVersion`.

**Tech Stack:** Python 3.12 stdlib (`http.server`, `urllib`, `unittest`), Rust stable (`cargo`), TypeScript extension (pi `ExtensionAPI`), Docker Compose, `opencode run --pure` as L2 probe.

**Skills:** @test-driven-development for every component, @verification-before-completion before each phase gate.

---

## Phase 0 — Repo bootstrap (this folder)

### Task 0: E2E proof against deployed keeper (FIRST — gates everything)

**Files:**
- Create: `e2e/deployed-baseline.sh`, `e2e/README.md`

**Step 1: Record live curls** — `/healthz` asserts 200; `/packs` asserts 401 without bearer; with bearer asserts 200 + captures member shapes (models/providers, values redacted) into `e2e/baseline-shapes.json`. Bearer comes from env only (`KEEPER_TOKEN`), never committed.
**Step 2: Run** `bash e2e/deployed-baseline.sh`; expected: all green except the known 403-vs-401 token item, recorded as OPEN in `e2e/README.md`.
**Step 3: Commit** `test: deployed e2e baseline`. No v2 code until this is green.

### Task 1: Create GitHub repo and push

**Files:**
- Modify: `.git` remote (new)

**Step 1: Create repo (no test — infra)**
```bash
gh repo create KSonny4/x-as-llm-api --public --source=. --push
```
Expected: repo exists, `main` pushed with design commit.

**Step 2: Verify**
```bash
gh repo view KSonny4/x-as-llm-api --json name,url
```
Expected: prints repo JSON.

### Task 2: Skeleton layout + compose

**Files:**
- Create: `keeper/server.py`, `keeper/Dockerfile`, `compose.yaml`, `.env.example`, `KEEPER_API.md` (stub: `# KEEPER_API — v2 draft`), `scripts/smoke.sh`
- Test: `keeper/test_server.py`

**Step 1: Write the failing test**
```python
# keeper/test_server.py
import unittest
class HealthTest(unittest.TestCase):
    def test_healthz_contract_exists(self):
        import server
        self.assertTrue(hasattr(server, "H"))
```
**Step 2: Run test to verify it fails**
Run: `cd keeper && python3 -m unittest test_server -v`
Expected: FAIL (`server` module not defined).

**Step 3: Write minimal implementation** — `server.py` with `GET /healthz → 200 ok`, stdlib only; `Dockerfile` (`python:3.12-slim`, `CMD ["python3","server.py"]`); `compose.yaml` (local dev: keeper :8080, `KEEPER_TOKEN: ${KEEPER_TOKEN:?…}` required); `keeper.nomad.hcl` (prod job: same image, Bao-backed secrets, health check on `/healthz`); `.env.example` (`KEEPER_TOKEN=`, `PORT=`); `scripts/smoke.sh` (`/healthz` assert, `NOMAD_ADDR`-agnostic: takes base URL arg).

**Step 4: Run test to verify it passes**
Run: `cd keeper && python3 -m unittest test_server -v` then `PORT=18080 KEEPER_TOKEN=t python3 server.py & sleep 1; curl -s localhost:18080/healthz; kill %1`
Expected: PASS, prints `ok`.

**Step 5: Commit**
```bash
git add keeper compose.yaml .env.example KEEPER_API.md scripts/smoke.sh
git commit -m "feat: keeper P0 skeleton (healthz, compose, smoke)"
```

---

## Phase 1 — Keeper v2 API (TDD, @test-driven-development)

### Task 3: Bearer auth + 404 discipline

**Files:**
- Modify: `keeper/server.py`
- Test: `keeper/test_server.py` (append)

**Step 1: Write the failing test**
```python
def test_packs_requires_bearer(self):
    # unauthenticated GET /packs must be 401; unknown path 404
```
**Step 2:** Run, expect FAIL. **Step 3:** Implement `_authed()` (`KEEPER_TOKEN` required, `Bearer` compare; refuse start if unset). **Step 4:** Run, expect PASS. **Step 5:** Commit `feat: bearer auth + 404 discipline`.

### Task 4: `GET /packs` values wire + ETag/304

**Files:**
- Modify: `keeper/server.py`, `KEEPER_API.md` (document v2 member shape)
- Test: `keeper/test_server.py`

**Step 1:** Failing test — seeded member with `credential.value` served when authed; `If-None-Match` → `304`; `Cache-Control: max-age=600`; seed via env `SEED_FILE` (test fixture JSON, never real secrets). Production seeds export live refs from Bao (`bao kv get secret/projects/pi-multi-providers/<NAME>`, excluding `*_UNAVAILABLE/*_RETIRED/*_INACTIVE/*_BANNED`); `KEEPER_TOKEN` comes from the same path.
**Step 2:** Run, FAIL. **Step 3:** Minimal `freeze()` from seed file + ETag. **Step 4:** PASS. **Step 5:** Commit `feat: packs values wire + etag`.

### Task 5: `POST /feedback` (202 spool, 422 validation)

**Files / steps:** same shape. Failing test: missing required field → `422` with `missing[]`; bad `errorClass` → `422`; valid → `202` + JSONL line in `FEEDBACK_LOG` tmp path. Implement, PASS, commit `feat: feedback spool`.

### Task 6: `GET /v1/providers` + `GET /v1/guide/:who`

**Files / steps:** Failing test — providers lists `baseURL/modelIDs/envVar/curl` per seed; every guide emits ONE OpenAI curl (`POST /v1/chat/completions`) regardless of upstream wire. Implement generators, PASS, commit `feat: dispenser endpoints`.

### Task 6b: Translator `keeper/translate.py` (OpenAI-out)

**Files:**
- Create: `keeper/translate.py`
- Test: `keeper/test_translate.py`

**Step 1: Write the failing tests** (fixtures only, no live calls) — OpenAI request → Anthropic body (system/message/tool mapping, `max_tokens` passthrough); Anthropic response → OpenAI `choices` (content, `tool_calls` with generated ids, `usage`); Anthropic SSE event → OpenAI chunk; Anthropic error → OpenAI-shaped error.

**Step 2: Run tests to verify they fail**

Run: `cd keeper && python3 -m unittest test_translate -v`
Expected: FAIL (`translate` module not defined).

**Step 3: Write minimal implementation** — `openai_to_anthropic(req)`, `anthropic_to_openai(resp)`, `anthropic_event_to_openai_chunk(ev)`, `anthropic_error_to_openai(err)`; `wire: openai` passthrough.

**Step 4: Run tests to verify they pass**

Run: `cd keeper && python3 -m unittest test_translate -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add keeper/translate.py keeper/test_translate.py
git commit -m "feat: OpenAI-out translator (anthropic both-ways)"
```

### Task 6c: `POST /v1/chat/completions` + `GET /v1/models` (OpenAI parity)

**Files / steps:** Failing test — chat completion via `wire: openai` seed route returns OpenAI `choices` shape (stubbed upstream); via `wire: anthropic` route returns identical shape through the translator; `stream: true` yields SSE `data:` chunks; `GET /v1/models` lists seeded models in OpenAI shape. Implement routes, PASS, commit `feat: OpenAI-parity endpoints`.

### Task 6d: `GET /v1/route/:model` (machine interface)

**Files / steps:** Failing test — authed call returns `{model, baseURL, api: "openai", auth: {scheme, value}, features, keeperPackVersion}` from seed; unauthed → `401`; unknown model → `404`. Implement, PASS, commit `feat: machine route endpoint`. Guides Task 9 then adds the Python (`urllib`) + Rust (`reqwest`) startup sketches consuming it.

---

## Phase 2 — Matrix + UI (deprecates llm-quota)

### Task 7: Matrix builder (port llm-quota grouping cases)

**Files:**
- Create: `keeper/matrix.py`
- Test: `keeper/test_matrix.py`

**Step 1:** Failing test — port the grouping cases from `~/git_projects/llm-quota/test/matrix.test.js`: email dedupe case-insensitive, email-in-name fallback, bare names → `unassigned`, inactive → `skippedInactive`. Cells carry probe state + optional AA score (tiebreak input, not ordering).

**Files:**
- Create: `keeper/matrix.py`
- Test: `keeper/test_matrix.py`

**Step 1:** Failing test — port the grouping cases from `~/git_projects/llm-quota/test/matrix.test.js`: email dedupe case-insensitive, email-in-name fallback, bare names → `unassigned`, inactive → `skippedInactive`.
**Step 2:** FAIL. **Step 3:** Implement `groupConnectionsByEmail` + `buildMatrix` in stdlib Python. **Step 4:** PASS (`python3 -m unittest test_matrix -v`). **Step 5:** Commit `feat: matrix builder (llm-quota parity)`.

### Task 8: `GET /api/v1/matrix|accounts|health` + `/` UI

**Files / steps:** Failing test — matrix endpoint returns rows/cols/diagnostics shape; `/` returns HTML containing table + `diagnostics.unassigned` section + `?refresh=1` bypasses cache. Implement server-rendered HTML (no framework), PASS, commit `feat: matrix UI`. Gate: open `http://localhost:8080/` in VS Code simple browser, eyeball rows.

### Task 7b: AA snapshot fetch (tiebreak input)

**Files / steps:** Failing test — fixture AA payload → scores indexed by model; fetch failure → last-good retained with stale flag. Implement daily fetch (`ARTIFICIALANALYSIS_API_KEY`, stdlib `urllib`, file cache), PASS, commit `feat: AA snapshot for tiebreak`.

### Task 9: `/guides`, `/signin`, `/report` pages

**Files / steps:** Failing tests — each page 200 + contains marker (`curl` block / re-mint steps / form posting to `/feedback`); `/report` round-trip writes a spool line. Implement, PASS, commit `feat: guides/signin/report pages`.

---

## Phase 3 — Probe worker (L1 → L2 CLI)

### Task 10: L1 curl probe

**Files:**
- Create: `probe/worker.py`
- Test: `probe/test_worker.py`

**Step 1:** Failing test — against local stub baseURL: `/models` 200 + tiny chat returns text ⇒ `ok`; connection-refused ⇒ `suspect`; stubbed 429 ⇒ `limited` (kept, backoff scheduled); stubbed 401/403 ⇒ `suspect` + feedback spooled. L1 uses the route's declared `wire` (openai → chat/completions, anthropic → v1/messages); a wrong-wire response is classified `misconfigured`, distinctly from `down`.
**Step 2–4:** Implement `probe_l1()` with `urllib`, PASS, commit `feat: L1 probe`.

### Task 11: L2 `opencode run` probe + states + `status.json`

**Files / steps:** Failing test — L1-fail + stubbed L2-pass ⇒ `degraded`; both fail ⇒ `down`; report event ⇒ `suspect` + instant re-probe. Stub the CLI via `PATH` fixture script. Implement `probe_l2()` (`opencode run --pure -m … "ping"`), state machine, `status.json` writer; wire worker as second compose service (`command: ["python3","/srv/probe/worker.py"]`). PASS, commit `feat: L2 probe + states`. Gate: `scripts/smoke.sh` extended (health → packs → guides → matrix → status → feedback round-trip) all green.

---

## Phase 4 — Extension repo rebuild (`KSonny4/pi-infinity-llm`)

### Task 12: Archive + strip to extension-only

**Files (in pi-infinity-llm checkout):**
- Create: `archive/pre-split` branch; `DEPRECATED-map.md` (where each removed piece lives now)

**Step 1:** `git checkout -b archive/pre-split; git push -u origin archive/pre-split; git checkout master`.
**Step 2:** Delete `keeper/ packs/ prototype/`, old e2e vs old keeper **from the pi-multi-providers tree** (canonical — carries the Zen-mint fix); keep `extension/`, tests, README (rewritten minimal → points at `KEEPER_API.md` in x-as-llm-api), `AGENTS.md` pin.
**Step 3:** Commit `chore: strip to extension-only (keeper lives in x-as-llm-api)`. No test (surgery, verified by Task 13).

### Task 13: Extension values mode (replaces `CONNECTION_KEY_ENV`)

**Files:**
- Modify: `extension/extensions/keeper.ts`
- Test: `extension/test/values.test.js` (run: `node --test`)

**Step 1:** Failing test — served `credential.value` injected as `Authorization: Bearer` + mirrored `x-api-key`; `signin` member surfaces re-mint command; no `CONNECTION_KEY_ENV` import remains.
**Step 2–4:** Implement, `npx tsc --noEmit && node --test`, PASS, commit `feat: values-mode credentials`.

### Task 14: Rust `keeper-helper` — mint + sign + shape

**Files:**
- Create: `helper/Cargo.toml`, `helper/src/main.rs`
- Test: `cargo test` (exact `u64` mint vectors vs known-good outputs from old `zen_mint.py`)

**Step 1:** Failing test — `mint` vectors (descending 48-bit IDs, `ses_` + base62 shape); `sign` maps credential JSON → headers JSON; `shape` normalizes a probe event.
**Step 2–4:** Implement (`mint-zen-session`, `sign`, `shape`; stdin JSON, stdout JSON, never log values), `cargo test` PASS, commit `feat: keeper-helper (mint/sign/shape)`.

### Task 15: Extension spawns helper (replaces in-TS mint)

**Files / steps:** Failing test — `User-Agent` + `x-opencode-session` present and fresh per request with the in-TS mint deleted. Implement spawn, PASS, commit `feat: extension uses keeper-helper`.

---

## Phase 5 — Cutover + deprecations

### Task 16: Contract freeze + deprecation notices

**Files:**
- Modify: `KEEPER_API.md` (mark v2 frozen), `~/git_projects/llm-quota/DEPRECATED.md`, `~/git_projects/pi-infinity-llm/DEPRECATED-map.md`

**Steps:** Gate per phase (units green + `smoke.sh` green + one real inference: curl chat, `pi --provider infinity-implement -p "ping"`, opencode L2) before the next phase starts. Rollback rehearsal first (Nomad job revert forth and back, smoke both ways), then cutover; red smoke or a user report within 24h reverts the job. Then: llm-quota `DEPRECATED.md` (pointer + parity evidence), move hostname, archive repo. Commit docs in each repo. @verification-before-completion before announcing done.
