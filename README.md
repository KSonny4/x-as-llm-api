# Keeper

Private free-model availability and an inference API for another service.

> **Verified sanity check: original zencli works on Nomad.** The unchanged
> original HTTP wrapper returned **200**, model `big-pickle`, answer
> `September 20, 2026.`, using the same key as the successful local CLI command.
> **Preserve original zencli and use it as the control.**
> [Exact receipt and reproduction](docs/zencli-sanity-check.md).
>
> **New Keeper API not yet deployed:** the modified candidate failed its earlier
> tests; those failures do not invalidate the successful original control.
> Production is unchanged. Instructions below describe the candidate contract,
> not a working public rollout. [Staging evidence](docs/keeper-staging-2026-09-20.md).

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

**Public rollout still requires successful Keeper integration and acceptance.**
The [fresh original zencli Nomad HTTP control](docs/zencli-sanity-check.md) passed;
its working path must be preserved. Earlier proofs are in `zencli/TRANSCRIPT.md`.
Neither the control nor those historical proofs establish the modified deployment. See [engineering guidance](docs/engineering-guidance.md),
[API contract](KEEPER_API.md), and [rollout/rollback](docs/keeper-all-models-rollout.md).

The private dashboard is at `/login`; it uses the administrator credential,
not the inference-only service token. Verified direct provider-key export uses
`/api/v2/credentials`; CLI-only success is explicitly non-exportable.
