# Protected baseline: original zencli works on Nomad

**Verified 2026-09-20 UTC / 2026-09-21 CEST: the unchanged original zencli returned HTTP 200 from its OpenAI-compatible endpoint on Nomad.** This is a fresh successful HTTP control, not merely a local CLI result or an inference from an old receipt.

## Binding user requirement

Preserve the original zencli. Use it as the sanity-check control when changing Keeper's integration. The user explicitly requested that this evidence be retained in Cognee and project documentation so later agents do not forget the working path.

Before diagnosing CLI availability, changing its invocation/configuration, or deploying a replacement:

1. Read this receipt and preserve the original source and pinned control image.
2. Compare the unchanged original HTTP wrapper and candidate on the same host, exact credential, model, and input. Record configuration differences; change one at a time.
3. Judge HTTP inference by HTTP status, actual returned model and usable generated content. For a direct CLI control, check exit status and the answer. Normal stderr progress is not failure.
4. Keep findings scoped to the tested key/model/transport/configuration. Direct Zen HTTP failures and cooldowns do not, by themselves, establish that genuine CLI inference failed. Respect actual CLI upstream limits when observed.
5. Fix the integration rather than replacing or editing the working control to match a failing candidate. Public rollout requires its own end-to-end acceptance.

The user does not want direct OpenCode HTTP checks to disqualify working CLI tokens. The intended integration reuses the proven CLI flow, without the newly introduced custom agent or forced step limit. Production safety and capability compatibility still require separate verification; this controlled test is not permission to expose arbitrary unauthenticated execution.

## Local control — passed

Exact command actually run:

```sh
opencode run --model opencode/big-pickle "whats the date"
```

Exit status: **0**. Genuine CLI output included:

```text
> build · big-pickle
$ date "+%Y-%m-%d %H:%M:%S %Z"
2026-09-21 00:56:02 CEST
[2026-09-21 00:56:02 CEST]
Monday, September 21, 2026.
```

`> build · big-pickle` and tool progress are normal CLI status output, including on stderr. Their presence is not an error. This local test alone would not establish Nomad HTTP success; the independent control below does.

## Original Nomad HTTP control — passed

| Evidence | Observed value |
| --- | --- |
| Job | `zencli-original-sanity-1789946002` |
| Allocation | `4c670783-351f-45d6-8846-9c551112c66f` |
| Node | `ovh-nomad-fresh`, `d9619812-d1da-b474-2723-ffca768fb5be` |
| Image | Original `registry.pkubelka.cz/zencli:main-1`, pinned by digest below |
| Credential reference | `OPENCODE_ZEN_RETIRED_1@bao:2`, matched to the successful local login; value never recorded |
| Endpoint | Original Go wrapper, container-loopback `POST /v1/chat/completions` |
| Requested / returned model | `big-pickle` / `big-pickle` |
| Prompt | `whats the date` |
| HTTP status | **200** |
| Assistant answer | **`September 20, 2026.`** |
| Operator exec status | **0** |
| Original source | Hashes unchanged before and after |
| Production | Keeper job version unchanged; no production switch |
| Cleanup | Temporary control job stopped |

The date is consistent with UTC still being September 20 while local CEST had crossed midnight. Compare time zones before interpreting date differences as a failed inference.

Immutable image:

```text
registry.pkubelka.cz/zencli@sha256:8e49713e8fa5c7f4a098382498c080dcd8ce44848abd0d034b24d915578b9151
```

Request:

```json
{"model":"big-pickle","messages":[{"role":"user","content":"whats the date"}],"stream":false}
```

Machine-readable observed receipt: [zencli-sanity-check.json](zencli-sanity-check.json).

## Reproduce the control, not a replacement profile

Use an isolated temporary Nomad batch allocation on the same node and the immutable image above. The successful control used Docker **bridge networking**, container-loopback HTTP with no published ports, 500 CPU / 1024 MiB, root HOME, a normal writable container filesystem, no host data mounts, dropped capabilities and `no-new-privileges`. It did **not** use the candidate's read-only-root/noexec-tmpfs profile.

Stage only the exact selected OpenCode credential into `/root/.local/share/opencode/auth.json` via private stdin and mode 0600. Never put credential values in arguments, job output, receipts, Git, or logs. A rotated key is a new identity requiring a new receipt.

The only control configuration supplied via `OPENCODE_CONFIG_CONTENT` was:

```json
{"enabled_providers":["opencode"],"provider":{"opencode":{"whitelist":["big-pickle"]}},"small_model":"opencode/big-pickle","autoupdate":false,"share":"disabled"}
```

This confines auxiliary calls to the same free model and pins behavior. **No custom agent, no tool/permission overrides, no forced step limit.** The original wrapper itself invokes genuine OpenCode with its existing `--pure` argument; it was not replaced with the candidate command or parser.

Launch the original binary inside that private container:

```sh
/srv/zencli/zencli -bind 127.0.0.1 -port 8099 -opencode-bin /root/.opencode/bin/opencode
```

From inside the same container, submit the JSON request above to `http://127.0.0.1:8099/v1/chat/completions` with `Content-Type: application/json`. Check HTTP 200, returned model and a usable answer. A `/v1/models` listing alone is not a pass. Sanitize output, stop the control, remove temporary auth, and verify original source/production remained unchanged.

The operator helper used for this receipt is `/tmp/keeper-deploy-preflight/original-zencli-nomad-sanity.py`; it depends on private operator credentials/configuration and is not a public standalone script. The durable reproduction specification is above, not that temporary path. The private original receipt is in `/Users/ksonny/.local/state/keeper-backups/20260920T212913Z/original-zencli-nomad-sanity.json`.

## Source protection and scope

Original source revision: `fd66590abdeb673cd4c1fbc76c2a4ee9735ef971` in the parent checkout, not the modified Keeper worktree. From the **parent checkout**, verify the protected original:

```sh
git diff --exit-code fd66590abdeb673cd4c1fbc76c2a4ee9735ef971 -- zencli/
```

The control also verified SHA-256 values for `zencli/main.go`, `zencli/Dockerfile`, and `zencli/entry.sh` before and after; the operator's guard is `/tmp/keeper-deploy-preflight/original-zencli-baseline.json`. The Git revision above is the durable source comparison, independent of that temporary file. The already-modified `wt/keeper-all-models/zencli` candidate is not the protected parent-checkout source. The immutable image digest independently identifies the executed control.

This proof establishes **one exact stored key × big-pickle × original zencli HTTP transport on Nomad**. It does not establish every key/model, native streaming/tool parity, direct-provider HTTP availability, the hardened candidate, or deployment of `keeper-coder` at the public endpoint. The temporary control is stopped, not a permanently running new service.

The earlier candidate's 403/timeouts and direct-provider limits remain observations of those different tests, not a retraction of this pass. The precise cause of the candidate/control difference has not yet been isolated.

## Durable memory

This receipt and the preservation requirement were stored permanently in Cognee dataset `pi_cognee_memory`. Read-back found the original Nomad HTTP 200 baseline. Recall using: `x-as-llm-api original zencli Nomad sanity zencli-original-sanity-1789946002 preserve unchanged original`.
