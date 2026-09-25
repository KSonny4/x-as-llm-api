# Keeper HTTP observability

Every request through the keeper `server` task emits **one JSON line on
stderr** (Alloy already ships stderr to Loki — no pipeline change needed;
query with `| json`). No secret values ever leave the process: credentials
appear only as a sha12 fingerprint, plus the principal class.

## Access-log record

```json
{"ts": "2026-09-21T22:38:49.654+00:00", "req": "probe-42", "trace": "",
 "method": "GET", "path": "/v1/models", "status": 200, "ms": 0,
 "principal": "service", "cred": "361c2d512c35",
 "err": "", "ua": "python-httpx/0.28.1"}
```

- `req` — `X-Request-ID` honored when sane (else minted 16-hex) and **always
  echoed back as a response header**. Put it in bug reports to jump straight
  to the log line.
- `trace` — W3C `traceparent` trace-id when the caller sends one (Tempo
  correlation without any SDK).
- `principal` — `none | service | admin | session`, computed the same way
  `route()` authenticates.
- `err` — machine-readable code from keeper JSON error envelopes
  (`inference_only_token`, `no_working_compatible_free_model`, …), `""`
  otherwise. Refusals are the point: a 403 now logs *why*.
- `ms` — handler latency to last byte (includes full SSE stream time).

## What tonight's 403 looks like

```json
{"method": "GET", "path": "/v1/models", "status": 403,
 "principal": "service", "cred": "361c2d512c35",
 "err": "inference_only_token", "req": "…", …}
```

`principal=service` + `err=inference_only_token` on an inference path means
the service token matched but scope routing refused it — keeper-side token
scope/config, not caller error, not backend dryness (dryness is 503
`no_working_compatible_free_model`).

## LogQL

```logql
# all refusals with reasons, last hour
{project="x-as-llm-api", service_name="keeper-server"}
  | json | status >= 400

# one request by ID (from the X-Request-ID response header)
{project="x-as-llm-api"} | json | req = "probe-42"

# scope refusals per credential fingerprint (is it one token or many?)
{project="x-as-llm-api"} | json
  | err = "inference_only_token"
  | count by (cred)
```

## PromQL (`/metrics` additions)

```
keeper_http_responses_total{route="inference",code="403"}   # refusals by route+code
histogram_quantile(0.95,
  rate(keeper_http_latency_ms_sum[5m]) / rate(keeper_http_latency_ms_count[5m]))
```

Route classes: `healthz login metrics inference pages session api_v2
api_v1 route_info other` (low-cardinality by construction — no IDs).

## Contract notes

- `route()` is untouched (pure, same return contract — all existing tests pass).
- `X-Request-ID` response header and the new `/metrics` series are additive;
  no `KEEPER_API.md` change needed.
- Implementation: `keeper/server.py` (`http_req_id`, `http_trace_id`,
  `norm_http_route`, `http_error_code`, `fp_cred`, `classify_caller`,
  `http_observe`, `http_access_record` + `H._serve`). Tests:
  `keeper/test_http_observability.py`.
