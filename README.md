# Keeper

Private free-model availability and an inference API for another service.

> **Verified sanity check: original zencli works on Nomad.** The unchanged
> original HTTP wrapper returned **200**, model `big-pickle`, answer
> `September 20, 2026.`, using the same key as the successful local CLI command.
> **Preserve original zencli and use it as the control.**
> [Exact receipt and reproduction](docs/zencli-sanity-check.md).
>
> **LIVE since 2026-09-21 (Nomad job `keeper` v12, images below):** the service API
> below is verified working on `https://keeper.pkubelka.cz` — service-bearer
> `keeper-coder` chat returned HTTP 200 on production. The original zencli
> control still passes alongside it and remains preserved.
> [Canary receipts](docs/keeper-uds-clock-repair.md) · [rollout/rollback](docs/keeper-all-models-rollout.md).
>
> Images (immutable, amd64):
> `registry.pkubelka.cz/keeper@sha256:84cbc9d5264066f193567fe12e6039336aa49b09877c159bdc2195f22a169cef`
> `registry.pkubelka.cz/zencli@sha256:521fd0aef081a57d0d01c54cb6fa6566c7dc1ad68777cff153251ccd90e52113`
>
> Transitional note: the genuine-CLI route is proven on frozen bits (canary:
> exact RETIRED_1/big-pickle/date HTTP 200s via private Unix IPC) but production
> CLI rows are still converging after the next scheduled discovery refresh;
> `keeper-coder` currently serves verified working direct-provider free routes.

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

**Production v12 is live and verified.** The [fresh original zencli Nomad HTTP control](docs/zencli-sanity-check.md)
still passes; its working path is preserved. Earlier proofs are in `zencli/TRANSCRIPT.md`.
Live receipts: service `keeper-coder` chat HTTP 200 on production (selected
`inclusionai/ling-3.0-flash-vl:free`); canary exact-CLI observation WORKING +
admin exact chat HTTP 200 (`big-pickle`, `Monday, September 21, 2026.`).
See [engineering guidance](docs/engineering-guidance.md),
[API contract](KEEPER_API.md), and [rollout/rollback](docs/keeper-all-models-rollout.md).

The private dashboard is at `/login`; it uses the administrator credential,
not the inference-only service token. Verified direct provider-key export uses
`/api/v2/credentials`; CLI-only success is explicitly non-exportable.


Latest candidate: [native CLI / transport repair](docs/keeper-transport-repair.md).
Free Zen direct routes are visible but `cli_required`, not futile inference
probes. Genuine CLI uses the native build agent with noninteractive permission
rejection, no custom agent/forced-step profile; it remains plain-text-only.
Transport-scoped cooldowns preserve actual CLI limits without importing direct
failures. Public rollout and real coding-agent compatibility need parent receipts.


Latest continuation: [Unix IPC and exact native clock repair](docs/keeper-uds-clock-repair.md) —
**deployed as v12 and canary-verified live.** CLI Docker bridge preserves the
controlled egress path; private authenticated Unix HTTP replaces host-loopback
IPC. Native ask-only shell bypass is closed by an immutable exact-date gate.
Update: daily per-key verification budgets shipped (5 inference checks/key/day,
oldest-first rotation, on-demand serving checks exempt) so verification stops
eating the quotas it measures. Operator-forced discovery refresh shipped
(admin-only `POST /api/v2/discovery/refresh`, at most one per hour, plus a
`Refresh inventory` dashboard button) — used on production to publish the
Unix-IPC CLI rows the same day instead of waiting for the daily cadence.
Remaining follow-ups: redacted bridge failure classification for flaky
fast-502s, upstream-stall characterization, and a nicer public landing page.
