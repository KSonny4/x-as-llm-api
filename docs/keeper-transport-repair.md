> Latest correction: [Unix IPC / exact-clock security repair](keeper-uds-clock-repair.md)
> supersedes this document's original host-network/ask-only profile. Schema is now
> 3; actual CLI clock execution is narrowly gated, never arbitrary bash.

# Native CLI / exact transport repair — deployable candidate, not rollout proof

Protected control: [original HTTP 200 receipt](zencli-sanity-check.md). The parent
checkout and immutable main-1 image are unchanged. Local tests do not establish
public deployment, provider availability, or generic coding-agent compatibility.

## Changes

- Genuine pinned OpenCode 1.18.31 built-in build agent, unchanged tool definitions,
  no custom keeper-api agent, no forced step count. `run --model opencode/<id>
  --format json --pure -- <prompt>`. JSON is native event rendering only.
- Global native ask policy, never `--auto`, `--yolo`, interactive or approval flags.
  Pinned noninteractive run rejects permission requests. Isolated HOME, exact-key
  auth file, scrubbed environment, free model whitelist/small_model, no external
  plugins/MCP and hardened no-host-mount runtime remain. This safety configuration
  is intentionally not the unrestricted protected control.
- Native permission-rejected tool events are never assistant output. Tool-only
  rejection has no final answer and returns 502. Completed tools, other execution
  errors, malformed events and credential reflections are not accepted. No fake
  tool schemas, tool results, continuation, or SSE are generated.
- Free OpenCode Zen direct transports remain visible with `cli_required`, original
  pricing and observation history; they are not checked, selected or exported.
  Inventory/pricing discovery is still necessary. Other providers retain all-key
  × all-eligible-model coverage. CLI identities are separate, service-only.
- Upstream cooldown and auth-invalid effects are credential × endpoint × protocol,
  not key-global. Model-specific denial stays connection-local. Sweep pacing and
  running-claim exclusion use the same transport boundary. Manual revocation,
  disabled inventory and credential generations remain global controls.
- CLI 429 and Retry-After now survive verification, including long cooldowns.
  Any successful eligible transport still makes the key healthy. Dashboard
  preserves its design and distinguishes policy blocks, historical observations,
  exact-transport cooldowns and ambiguous legacy cooldowns.

## Compatibility (not a live agent-client certification)

| Request feature | Genuine CLI route | Compatible direct routes |
| --- | --- | --- |
| Plain string system/user/assistant history | Flattened genuine CLI prompt | Native/translated history |
| Client function tools and tool history | Unsupported; never dropped | Supported per protocol allowlist |
| `stream:true` | Unsupported; no buffered imitation | Genuine incremental SSE |
| Generation controls, JSON output mode | Unsupported | Protocol-specific mapping only |
| Model-internal local tools | Native definitions, approval rejected | Not applicable |
| Actual provider key export | Never | Fresh exact verification required |

A minimal OpenAI SDK request with only `model` and `messages` is compatible.
Ordinary tool-using/streaming coding agents **cannot use the CLI-only route**.
They require a separately working compatible direct provider. No such public
client success is claimed by these local tests. Unsupported valid requests with
no compatible working route return OpenAI-shaped 503; unsafe/malformed extensions
are rejected with 400. Private CLI rejects unsupported fields with 400.

## Parent-owned exact-key canary

1. Build reviewed frozen Keeper and CLI commits as immutable amd64 images. Keep
   control image/source unchanged. Stage a private canary with separate temporary
   durable database, only the approved exact `OPENCODE_ZEN_RETIRED_1@bao:2` seed,
   and separate admin/service/internal bearers via private input. No values in
   arguments, shell history, logs or receipts. Do not copy any control success into
   `availability.db`. All inference/registry/Bao/Nomad actions belong to parent.
2. Let fresh authoritative inventory/pricing create the `big-pickle` CLI identity.
   Authenticated `GET /api/v2/catalog`: find key `id` by exact `reference`, and
   model `id` where provider=`opencode-zen`, model=`big-pickle`, protocol=`zencli`,
   base_url=`http://keeper-zencli/v1`. Verify active/not revoked, free/fresh pricing,
   no future retry_at. The corresponding direct row must be `cli_required`.
3. Administrator `POST /api/v2/checks` with
   `{"credential_id":"<exact key id>","model_id":"<CLI model id>"}`.
   Expect 202 and one eligible pair (possibly sharing an existing background job).
   Poll catalog locally until that exact CLI connection has a **new** working
   check; record exact connection/model/credential IDs, timestamp, protocol,
   returned model, status and usable answer only. Actual CLI limits must be
   respected; do not bypass cooldown or import the protected receipt.
4. Administrator `POST /v1/chat/completions` using the CLI **catalog ID** as model,
   messages `[{"role":"user","content":"whats the date"}]`, no generation
   controls or stream. Bare big-pickle is ambiguous across retained identities.
   With the single-key canary, a success unambiguously uses the exact selected key
   through Keeper selection and the bridge, not the original control endpoint.
5. Use the separate service bearer for a real minimal OpenAI client request:

   ```python
   import os
   from openai import OpenAI
   client = OpenAI(base_url=os.environ['CANARY_OPENAI_BASE_URL'],
                   api_key=os.environ['KEEPER_SERVICE_TOKEN'])
   reply = client.chat.completions.create(
       model='keeper-coder', messages=[{'role':'user','content':'whats the date'}])
   assert reply.model == 'big-pickle'
   assert reply.choices[0].message.content.strip()
   ```

   The alias may select other working models if background checks established
   them; record actual returned model and exact selection history, never call a
   different route proof of big-pickle. Repeat the exact admin-ID request for that
   proof. A tool-required native rejection is a real candidate failure, not proof
   against the protected original. Compare same host/key/model/input before
   changing any remaining configuration difference.
6. Verify service bearer cannot reach admin/catalog/credential/internal endpoints.
   Verify CLI-only stream/tools requests fail explicitly. Then public cutover and
   dashboard checks, and allocation replacement/durability proof, require separate
   parent receipts. A private canary is not public deployment.

## Migration / rollback

`Store` transactionally upgrades av_schema 1 → 2. Back up SQLite with WAL using
its backup API first. New transport-limit and pacing tables are additive; model,
connection, check, feedback, job and selection history is not deleted.

V1 recorded global key cooldown without source duration. For each key with an
applied, finished rate_limited observation, migration conservatively copies the
old maximum deadline to **every evidenced endpoint/protocol**, then clears only
that attributed aggregate. Connection retry_at remains intact. Thus direct-only
rate evidence does not limit CLI; mixed direct+CLI evidence retains CLI limits.
Historical mixed evidence can conservatively over-delay an evidenced transport;
no precise duration reconstruction is claimed. With no source evidence, the old
global cooldown remains and is labelled `legacy_scope_unknown`. It is not a CLI
observation. Old revoked is ambiguous (upstream versus manual) and remains global
pending operator review; migration never auto-unrevokes it. A new credential
value must have a new generation identity. Migration is idempotent on restart.

Stop new workers before rollback. Pre-repair code rejects schema 2: restore its
pre-upgrade availability database backup offline when reverting that code, while
preserving the failed DB for analysis. Do not overwrite probe.db or delete host
data. Do not restore revoked/rotated secret generations. Rolling back all the way
to old Keeper also removes the inference service principal/API; report downtime.

## Local evidence

`keeper/test_transport_policy.py`: red→green policy, exact upstream limits/auth,
CLI 429, direct-only/mixed/unknown-scope v1 migration, restart, exact bridge
selection after direct rate history, scoped pacing and inflight auth fencing.
`zencli/native_cli_test.go`: real pinned CLI + synthetic loopback OpenAI upstream;
plain answer, genuine tool definitions, exact auth read, bash environment/parent
proc/auth attempt, task and webfetch rejection, auxiliary same-key/model checks.
`secure_test.go` verifies merged native permission rules and scrubbed argv/env.
`browser-smoke.cjs` red→green policy actions and legacy cooldown labels, retaining
mobile overflow, XSS, discovery warnings and token lifecycle coverage.

## Bounded dashboard review corrections

Immutable-e1ecb50 findings D1/D2 were checked against the repaired candidate, not
interpreted as provider evidence. Key snapshots now include `admission_reason`
independently of aggregate health and model rows: disabled, revoked, unsupported,
or signin_required. Model-less/Unassigned keys stay accounted for; their panels
explain the admission block and disable the otherwise zero-work Check key action.

`test_dashboard.py` supplies actual domain/API snapshots to the browser smoke.
The direct-rate-history snapshot proves the never-checked CLI is unknown, has no
retry timestamp and can begin checking. After an actual synthetic CLI rate-limit
result, its same-transport unchecked sibling has an applicable cooldown but still
no observation/timestamp. Browser labels distinguish “No observation yet” from
“Last observation: rate limited” and name the same-credential/endpoint/protocol
cooldown policy. The unrelated direct history remains unchanged. These tests do
not bypass cli_required or induce provider quotas. D2's admission assertion and
new browser explanations were red before the correction and green afterward.
The existing layout, Unassigned accounting and any-success owner health remain.
