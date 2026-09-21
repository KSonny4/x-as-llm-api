# Docker-bridge egress, private Unix HTTP and exact native clock

This supersedes the host-network/ask-only CLI candidate, not the protected
[original zencli control](zencli-sanity-check.md). Original source/image remain
unchanged. Parent owns live evidence, rollout and secrets. Local tests alone do
not make this candidate ready for public deployment.

## New parent-reported controlled evidence

On the same Nomad node, exact `OPENCODE_ZEN_RETIRED_1@bao:2`, `big-pickle`, and
`whats the date`, candidate `2e93860` under Docker host networking reported genuine
upstream rate errors and timed out. Changing **only** Docker network_mode to
bridge, with the same image/nonroot/readonly/noexec/native ask configuration,
returned genuine zero-cost model events in seconds (exit 0). The model attempted
bash command exactly `date`, which was auto-rejected, leaving tool-calls without
an answer. Original main-1 again returned HTTP 200 immediately after the candidate
timeout. These are parent-supplied observations, not a worker deployment receipt.

This isolates the tested network-mode regression and clock permission gap.
It does not prove host networking always fails, every key works, or that real
provider limits can be ignored. Noexec/nonroot protections are retained.

## Private IPC / network boundary

- Keeper stays Docker host networking, bound `127.0.0.1:8102` behind the existing
  public tunnel. CLI uses Docker **bridge**, no published/reserved internal TCP
  port, no CNI or node-wide network changes.
- Both tasks use authenticated HTTP over the Unix socket
  `/alloc/data/keeper-zencli/http.sock` (`KEEPER_ZENCLI_SOCKET`). Nomad's existing
  shared allocation directory is IPC only, not the durable database. CLI creates
  its child directory as UID65532 mode 0700 and socket 0600; root Keeper connects.
  No seed/admin/service credentials or Keeper DB are mounted into CLI.
- Go refuses foreign/permissive/symlink directories, non-socket paths and live
  listeners. Only its owned stale ECONNREFUSED socket can be replaced. Internal
  bearer auth still applies to every HTTP route, even local Unix callers.
- Python uses stdlib AF_UNIX HTTP, fixed endpoint allowlist, existing timeouts and
  response-size limit. No DNS, proxy, redirect or TCP fallback.
- `http://keeper-zencli/v1` is an explicit **logical authority over Unix IPC**,
  not a hostname to resolve or a provider-key-export endpoint. Old loopback model
  IDs remain historical/unsupported; fresh discovery produces new exact IDs and
  fresh checks are required. Old success is never imported.

## Concrete shell security fix and minimal clock allowance

Pinned official v1.18.31 `packages/opencode/src/tool/shell.ts` checks AST command
nodes (`source` lines 119–124, `collect` 392–410); an empty pattern set skips ask
(lines 282–290), then the full input executes (631–639). Thus native ask alone is
not a complete raw-shell security boundary. A real pinned-CLI hermetic regression
**created a marker file with redirect-only `> <marker>` under the previous
ask-only profile**. Returning 502 afterward would not undo that execution.

Exact native `bash: {"*":"ask","date":"allow"}` is therefore backed by an
immutable restricted-shell gate, not trusted as a standalone sandbox:

- Preserve native build agent and native bash definition. No custom tool/plugin,
  agent, fake schema or modified OpenCode binary.
- Fixed config.shell `/usr/local/libexec/keeper-clock/sh` is an image symlink to
  the same Go executable. Startup verifies identity/executable permissions and
  fails if absent/foreign; OpenCode must not fall back to a real shell.
- Gate accepts **only argv `['-c','date']`**, byte-for-byte. No login/interactive
  args, options, `date *`, format strings, substitutions, assignments, operators,
  redirections, PATH lookup or shell interpretation.
- Accepted input directly execs `/bin/date`, working directory `/`, fixed
  `LANG=C`, `LC_ALL=C`, `TZ=UTC`, minimal PATH and no inherited credentials, HOME,
  startup files or provider/internal environment. Denials emit a fixed safe
  message, never the raw input.
- Parser accepts a completed tool only if it is native bash input.command exactly
  `date` with explicit successful exit metadata. Tool output is not returned as
  assistant text. Text preceding a tool cannot stand in for a final answer:
  actual subsequent generated text and terminal stop/length are required.
  All other completed tools/nonzero results fail; native permission rejections
  remain separate from assistant text. No continuation is manufactured.

Tests use the real pinned CLI against a synthetic upstream. Exact clock execution
produces UTC output received by the model's next request and real final events.
Redirect-only, grouped redirects, assignment/substitution, function, operators,
newlines, PATH/env, workdir and date-option attempts cannot create/exfiltrate
markers. Existing read/bash/task/webfetch/grep/glob/write secret-isolation tests
remain. No provider network or paid calls are used by these tests.

## Schema 3 and rollback

Take a SQLite/WAL-consistent backup before upgrade. Schema 1 first receives the
previous exact-transport migration; schema 1/2 then upgrades transactionally to 3.
`av_transport_inheritance` copies only **active, evidenced prior CLI** cooldown or
auth-invalid policy from the old loopback CLI endpoint to the new logical IPC
authority. Existing applied/finished CLI observations must support the class.
Absolute deadlines are copied once, never renewed. Expired/no-source/direct-HTTP
limits are not copied. Old rows/history and global manual/ambiguous revoked flags
remain. New connections retain unknown/null observations, even when blocked by
inherited policy. Catalog/UI identifies `inherited prior CLI endpoint` and its
source base URL; it is not a new transport observation or Working proof.

A fresh canary database isolates rollout state, **not** permission to bypass a
known applicable limit. Parent must check exact selected-key scope/deadline and
record ambiguity; do not resurrect the erroneous direct→CLI attribution.

Rollback: stop workers, retain failed DB, restore the pre-upgrade availability DB
backup offline when reverting to schema-1/2 code. Preserve probe.db/durable host
data and credential generations. IPC data is ephemeral; stale socket recovery
is independent of database durability. Do not roll back secrets.

## Parent canary gate — required before readiness/review

1. Build both frozen images amd64. Verify CLI gate symlink/executable, UID65532,
   readonly/noexec runtime, Docker bridge, no internal TCP ports, and private
   socket ownership/root Keeper connectivity in the actual allocation.
2. With separate administrator/service/internal bearers, fresh authoritative
   discovery and approved exact key, target the `big-pickle` **new CLI catalog ID**
   (`base_url=http://keeper-zencli/v1`) through `POST /api/v2/checks` using exact
   credential_id + model_id. Respect current and inherited applicable cooldowns.
3. Require a new working exact CLI observation, then administrator
   `POST /v1/chat/completions` with that catalog ID and only
   `messages:[{"role":"user","content":"whats the date"}]`. Inspect actual
   model, usable final text, clock tool success and cost evidence privately.
   Compare unchanged main-1 on the same host/key/model/input, not imported history.
4. Exercise a minimal real OpenAI SDK client with the separate service bearer,
   model `keeper-coder`, messages only. Confirm selected route/actual model.
   Verify other principals cannot access admin/credential/IPC endpoints.
5. Parent sends explicit canary result back to writer. **Do not conclude ready
   or start final reviews until this result arrives.** Public rollout, dashboard
   checklist and allocation-replacement durability remain separate parent gates.

CLI remains plain-history-only for consumers: ordinary tool-using/streaming
agents and generation controls require an actually compatible direct backend.
The single internal clock allowance is not generic coding-agent compatibility.
