# zencli — genuine OpenCode, isolated per request

This is the existing Go bridge reused as Keeper's **private text-only backend**.
The historical direct CLI/Nomad proofs remain in `TRANSCRIPT.md` and
`docs/zencli-nomad-proof.txt`. This hardened build needs fresh parent live proof.

## Private interface

`KEEPER_ZENCLI_TOKEN` is mandatory. The listener is always
`127.0.0.1:8099` (port flag allowed); there is no anonymous/default-account mode.
All endpoints require the internal bearer, not the public service/admin bearer.

- `POST /internal/catalog`: Keeper supplies `{"models":[{"model":"exact-id",
  "verified_at":<pricing epoch>} ]}` from fresh authoritative free discovery.
  Eligibility expires after 24h; no static seven-model cap/list.
- `GET /v1/models`: only current allowlisted routes and honest capabilities.
- `POST /v1/chat/completions`: exact model + plain string messages. Private
  `X-Keeper-Provider-Key` carries the exact selected credential. No default auth.
  Returns actual parsed CLI generated text. Provider values are never returned.

The public front door remains Keeper's inference-only `keeper-coder` alias.
This interface is internal, not a separate consumer integration.

## Capabilities

Retains the proven `buildPrompt` text mapping for system/multiturn messages.
That mapping flattens roles; it is not lossless role/tool parity. Unknown fields,
tools/tool history, generation controls and `stream:true` are rejected, never
silently ignored. Historical word-chunked SSE is **not** used in this build.

## Execution safety

- Genuine CLI pinned to **1.18.31**, absolute executable fixed at deployment.
- Fresh per-request 0700 HOME/XDG dirs; auth file 0600 with selected key only.
- Scrubbed environment: no inherited provider/default credentials, Keeper
  bearers, proxy settings, project plugins or shell startup.
- Native built-in build agent and genuine tool definitions, no forced step limit.
  Global `permission: {"*":"ask"}` uses pinned noninteractive run auto-rejection;
  no approval flags, project config/external plugins or MCP. Tools cannot execute.
- Exact `opencode/<model>` plus provider model whitelist. `small_model` is the
  same free model, preventing an auxiliary paid-model choice.
- `run --format json --pure -- <prompt>`; the separator stops
  a prompt from becoming flags. `--pure` alone only disables external plugins.
- 110-second wall timeout, bounded output, process-group kill, temp cleanup.
  Accept only usable raw text events with stop/length finish; errors, completed tools,
  malformed/empty output and credential reflection are failures. Native rejected
  tool events are not assistant text. A tool-only rejected run has no final
  answer and returns 502; the bridge never fabricates continuation.
- Non-root read-only sidecar, no host data/secret mounts, all Linux capabilities
  dropped and no-new-privileges. Shared host network only for private loopback;
  authenticated requests remain mandatory even from the same node.

Source checked at tag `v1.18.31`: `agent/agent.ts` merges user ask permissions
after native build defaults; `cli/cmd/run.ts` rejects permission requests unless
explicitly auto-approved. JSON changes event rendering, not the agent. The
native truncation-directory traversal exception does not permit read execution.
`native_cli_test.go` runs the real pinned binary against a synthetic loopback
upstream: plain answer succeeds; exact auth-file read, environment/auth bash,
subagent task and webfetch are rejected, with genuine definitions visible to
the model. Title generation remains confined to the same exact free model/key.
This is local safety evidence, not a live provider or Nomad receipt.

## Build / tests

```sh
(cd zencli && go test -race ./...)
# Required predeploy native execution proof with the pinned genuine binary:
(cd zencli && KEEPER_TEST_OPENCODE_BIN=/absolute/path/opencode go test -race ./...)
docker build --platform linux/amd64 -f zencli/Dockerfile -t keeper-zencli:check .
```

Historical `entry.sh` / `zencli-nomad.hcl` are old batch-proof artifacts, not the
new service entrypoint. Do not stage a shared default auth file for this service.
Parent owns live deployment and internal token provisioning; see root rollout doc.
