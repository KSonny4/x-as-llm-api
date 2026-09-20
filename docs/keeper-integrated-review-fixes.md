# Integrated review corrections

**Later baseline receipt:** [original zencli works on Nomad](zencli-sanity-check.md)
through its unchanged HTTP wrapper (HTTP 200, `big-pickle`). Preserve it as the
control when integrating these changes. The local/security checks below do not
establish that the modified CLI configuration reproduces that working behavior.

Review base: `d751be8` (2026-09-20). These corrections follow the independent
spec and security reviews; they are not a live deployment receipt.

| Finding | Correction | Regression evidence |
| --- | --- | --- |
| F1: obsolete free CLI eligibility survives partial discovery | Publish authoritative negative Zen pricing even when every key inventory fails. Atomically invalidate cached same-endpoint protocol identities and derived CLI identities; preserve history, original endpoint boundaries and newer evidence; fence in-flight checks. Missing inventory alone still preserves last-good facts. | `keeper/test_catalog_invalidation.py`: paid, unknown and removed pricing; one/all key failures; sidecar admission; protocol change; old evidence; unrelated endpoint/provider isolation. Original four paid/unknown cases failed before the fix. |
| F2: legacy responses call CLI success direct proof | Mixed views identify `exact_transport`, include protocol metadata, and retain CLI successes only as L2—not L1. Key health remains any-success without misrepresenting the transport. | `keeper/test_legacy_transport_evidence.py`: bridge-only success through health, key-queue and matrix endpoints. Original response label failed before the fix. |
| S1: credentials split across stream fragments | Check logical incremental text/tool-argument channels before releasing incomplete credential prefixes. Bound pending buffering; reject post-terminal deltas and changes to atomic tool identity. Static model metadata does not turn normal streams into buffered responses. | `keeper/test_service_security.py`: split content and tool arguments failed before the fix; incremental JWT/free-model metadata test also caught and prevented over-buffering. |
| S2: malformed requests quarantine healthy keys | Validate shared parameter types/ranges and message/tool structure before selecting credentials. Treat upstream HTTP 400/422 as request rejection, finish the attempt without changing health or feedback, and do not retry it across keys. | `keeper/test_service_security.py`: fourteen malformed requests and four upstream request-error variants failed before the fix. |
| S3: threaded session mutation races | One short session lock covers expiry, lookup, login insertion and logout removal. No network/inference is performed under it. | `keeper/test_session_concurrency.py`: deterministic concurrent expiry/login mutation failed before the fix; login and logout cases pass. |
| F3/S4: hidden discovery/bridge failures | Persistent incomplete-inventory and bridge warnings, plus per-key last-attempt/last-success diagnostics. Inactive historical generations do not falsely flag current inventory as incomplete. | `keeper/browser-smoke.cjs`: real browser with synthetic fixtures, including error visibility, 26 models, XSS safety, token clearing/expiry and mobile overflow. The separate initial discovery-warning browser case failed before the UI fix. |

## Validation

Parent fresh local checks after corrections:

- Keeper: **268 passed**; probe: **46 passed**; scripts: **11 passed**.
- Go race/config suite: **11 passed**, including genuine OpenCode v1.18.31
  effective deny-all configuration. No provider inference is used by that check.
- JavaScript syntax, Nomad formatting, `git diff --check`, secret tripwire: pass.
- Browser regression uses only synthetic credentials and mocked API responses.

The public inference principal remains non-expiring and has no Keeper usage,
rate or concurrency quotas. Protocol validation and bounded secret-safe stream
buffering do not implement a customer usage quota. Upstream limits still apply.

Deployment is gated on re-review of these changes, rebuilt immutable amd64
Keeper image, refreshed legacy database backup, and fresh live inference and
application-state persistence evidence. The unchanged CLI image can remain
pinned to its separately verified `d751be8` digest.
