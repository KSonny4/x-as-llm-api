"""Best-effort OTLP/HTTP+JSON span export to Grafana Cloud Tempo. Stdlib only.

Env-gated: TEMPO_OTLP_USER + TEMPO_OTLP_TOKEN must both be set or every
entry point is a silent no-op (local dev, unconfigured deploys). Endpoint
defaults to the meowlabs stack; override with TEMPO_OTLP_ENDPOINT.
Never raises, never blocks serving: the POST runs on a daemon thread and
all failures are swallowed. No secret values, prompts, or bodies ever
leave the process — only route/code/principal/error-code/duration.
"""
import base64
import json
import os
import secrets
import threading
import time
import urllib.request

DEFAULT_ENDPOINT = ("https://tempo-prod-25-prod-gb-south-1.grafana.net"
                    "/otlp/v1/traces")
SKIP_ROUTES = {"/healthz"}
SKIP_PREFIXES = ("/metrics",)


def tempo_config():
    """(endpoint, user, token) or None when unconfigured."""
    user = os.environ.get("TEMPO_OTLP_USER", "")
    token = os.environ.get("TEMPO_OTLP_TOKEN", "")
    if not user or not token:
        return None
    return (os.environ.get("TEMPO_OTLP_ENDPOINT", DEFAULT_ENDPOINT),
            user, token)


def fresh_trace_id():
    return secrets.token_hex(16)


def span_payload(trace_id, name, start_ns, end_ns, attrs):
    otlp_attrs = [{"key": str(k), "value": {"stringValue": str(v)}}
                  for k, v in attrs.items()]
    return {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name",
             "value": {"stringValue": "keeper"}}]},
        "scopeSpans": [{
            "scope": {"name": "keeper"},
            "spans": [{
                "traceId": trace_id,
                "spanId": secrets.token_hex(8),
                "name": name,
                "kind": 1,
                "startTimeUnixNano": str(start_ns),
                "endTimeUnixNano": str(end_ns),
                "attributes": otlp_attrs,
                "status": {"code": 1},
            }],
        }],
    }]}


def _post(endpoint, user, token, payload):
    cred = base64.b64encode(("%s:%s" % (user, token)).encode()).decode()
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Basic " + cred,
                 "Content-Type": "application/json",
                 "User-Agent": "keeper-verify/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read(64)


def emit_request_span(trace_id, route_cls, code, ms, principal, err):
    """Fire-and-forget one server span per request. Returns False when
    skipped (unconfigured, health/metrics noise) — never raises."""
    try:
        if route_cls in SKIP_ROUTES or route_cls.startswith(SKIP_PREFIXES):
            return False
        cfg = tempo_config()
        if cfg is None:
            return False
        endpoint, user, token = cfg
        tid = trace_id if trace_id else fresh_trace_id()
        now = time.time_ns()
        payload = span_payload(
            tid, "keeper.request", now - int(ms * 1e6), now,
            {"http.route": route_cls, "http.status": code,
             "keeper.principal": principal, "keeper.error": err or "",
             "keeper.duration_ms": int(ms)})
        threading.Thread(target=_post, args=(endpoint, user, token, payload),
                         daemon=True).start()
        return True
    except Exception:
        return False
