# Keeper

Private free-model availability and an inference API for another service.

> **Not yet deployed:** the private OVH candidate found no usable free route.
> The hardened genuine CLI was rejected (403); direct checks were rate-limited.
> Production is unchanged. These are candidate consumption instructions, not a
> working public API receipt. [Staging evidence](docs/keeper-staging-2026-09-20.md).

- **Target base URL:** `https://keeper.pkubelka.cz/v1`
- **Model:** `keeper-coder`
- **Authentication:** separate, non-expiring `KEEPER_SERVICE_TOKEN`
- **Scope:** inference only; no dashboard, admin access or provider-key export.
- **Quotas:** no Keeper usage quotas or per-token rate/concurrency caps. Actual
  upstream free-tier limits/cooldowns still apply; no paid fallback.

`keeper-coder` selects the highest Coding Index verified working **compatible**
free backend across providers. Unmatched models remain honestly unscored. It
retries alternative keys before a weaker model, within a finite attempt budget.
Exact private credential requests never substitute models.

## Secure token retrieval

For the authorized operator, provision the other service's secret store from
Bao `secret/projects/pi-infinity-llm/KEEPER_SERVICE_TOKEN`, field `token`.
Do not print, commit or put the token in browser storage. For a local process:

```sh
set +x
export KEEPER_SERVICE_TOKEN="$(bao kv get -field=token secret/projects/pi-infinity-llm/KEEPER_SERVICE_TOKEN)"
```

Minimal request (also compatible with the genuine Zen CLI text backend):

```python
import json, os, urllib.request
body = {"model": "keeper-coder", "messages": [{"role": "user", "content": "Reply Hello."}]}
request = urllib.request.Request(
    "https://keeper.pkubelka.cz/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={"Authorization": "Bearer " + os.environ["KEEPER_SERVICE_TOKEN"],
             "Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=120) as response:
    result = json.load(response)
print(result["choices"][0]["message"]["content"])
```

## Capabilities and verification

Direct backends support compatible native/translated OpenAI chat, tool calls and
real streaming. The genuine `zencli` backend is **text-only**, with flattened
system/multiturn history; it rejects tools, generation controls and `stream:true`.
It does not pretend its historical buffered SSE is real streaming. Requests are
never silently weakened to fit a backend. Paid search/plugins and routing/model
fallback overrides are rejected.

**Public rollout is blocked on successful approved free-provider inference.**
Historical genuine-CLI proofs are in `zencli/TRANSCRIPT.md`; they are not receipts
for this hardened deployment. See [engineering guidance](docs/engineering-guidance.md),
[API contract](KEEPER_API.md), and [rollout/rollback](docs/keeper-all-models-rollout.md).

The private dashboard is at `/login`; it uses the administrator credential,
not the inference-only service token. Verified direct provider-key export uses
`/api/v2/credentials`; CLI-only success is explicitly non-exportable.
