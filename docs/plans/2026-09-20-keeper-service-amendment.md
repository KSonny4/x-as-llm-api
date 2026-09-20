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
