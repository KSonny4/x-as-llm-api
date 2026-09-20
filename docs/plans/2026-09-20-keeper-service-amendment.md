# Approved amendment: private service inference

The user's latest approval supersedes the original no-new-gateway boundary only for this bounded addition. Their other service receives ONE manually provisioned non-expiring inference-only bearer (`KEEPER_SERVICE_TOKEN`, parent provisions in Bao/env). It is separate from the administrator bearer and browser session. No signup, customer management, billing, Keeper usage quotas, token expiry, or per-token rate/concurrency caps.

Service access is limited to `/v1/models` and `/v1/chat/completions`. The advertised `keeper-coder` alias opts into selection of the highest Artificial Analysis Coding Index among verified working, compatible, eligible free routes across all providers; unscored fallback is explicit. Upstream cooldowns and no-paid-fallback evidence remain binding. Exact private credential APIs never substitute models. Provider credentials and administrative state remain inaccessible to the service token.

Preserve supported OpenAI request, tool-call and streaming semantics; reject unsupported features rather than silently discarding them. Bounded fallback is allowed before any stream output only. Actual upstream failure becomes precise connection feedback. Errors must not reveal keys or provider bodies. Parent alone issues the bearer, deploys, and performs live validation.

## TDD execution addition

1. Fix reviewed foundation defects with observed failing then passing regressions.
2. Build shared verified selection and versioned authenticated admin APIs; test freshness, precise feedback, CSRF/session and secret boundaries.
3. Add daily Coding Index cache, conservative matching, dark all-model Accounts/Models dashboard.
4. Test separate service-principal allowlist/non-expiry, highest compatible free alias selection, paid/unknown exclusion, bounded failover, nonstream/stream/tool semantics and redaction; implement on the shared availability foundation.
5. Prepare packaging and verified durable Docker bind (parent-confirmed volumes enabled): `/opt/nomad-volumes/keeper:/var/lib/keeper`. No local deployment. Run folder-local regression and fake-provider end-to-end checks. Report unsupported protocol features honestly.

## User correction: reuse the proven genuine Zen CLI backend

The repository already contains live genuine-CLI and Nomad proof in
`zencli/TRANSCRIPT.md` and `docs/zencli-nomad-proof.txt`. Direct HTTP denial is
not evidence that this distinct backend is unavailable. The user explicitly
approved integration of that existing Go bridge, not a new parallel gateway.

Parent approved a private authenticated loopback sidecar (1024 MiB based on the
prior measured CLI requirement), isolated from Keeper's DB/admin secrets. Each
request supplies the exact selected Zen credential and a model from Keeper's
fresh authoritative free catalog. Never use a default CLI login, static seven-
model eligibility list, paid fallback, or old CLI evidence as direct-API proof.
Persist separate `zencli` transport identities; bridge-only success cannot be
exported as a verified direct provider configuration.

Retain existing plain-text system/multiturn prompt mapping, explicitly labelled
flattened text-history semantics. Reject tools, unsupported generation controls
and streaming on this bridge unless implemented faithfully; its old buffered
word-SSE is not token-realtime. Direct adapters remain available for richer
compatible requests. No new user quotas, expiry, signup or customer product.

Before execution, verify deny-all built-in tool/permission configuration against
genuine OpenCode source; `--pure` disables external plugins, **not tools**.
Use isolated per-request HOME/XDG auth/config, scrub inherited secrets, raw JSON
text-event parsing, an end-of-options separator before prompts, bounded time and
output, cleanup, and container isolation without host data mounts. An independent
internal bearer (different from both public principals) is parent-provisioned.

TDD addition: exact-key/model isolation and concurrent temp cleanup; deny-tool
configuration and scrubbed environment; unknown/paid models rejected; no default
account; raw events only produce usable text; capability rejection; independent
SQLite direct/bridge observations; bridge blocked from private key export; alias
uses verified bridge for compatible text requests; packaging/loopback/internal
auth checks. Root README and engineering guidance document usage with live proof
explicitly pending parent deployment/verification.
