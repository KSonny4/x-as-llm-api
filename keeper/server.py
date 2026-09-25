#!/usr/bin/env python3
"""Keeper v2 (Wave 2). Stdlib only.

Values API + OpenAI-out chat + matrix UI + guides, behind one discipline:
Bearer $KEEPER_TOKEN on everything except GET /healthz; refuse to start
without a token. Pure routing (route()) stays hermetic for tests; the
handler only does sockets. Upstream HTTP goes through module-level
``urlopen`` so tests can stub it (no live calls in the suite).
"""
import hashlib
import html
import json
import os
import resource
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aa
import api_v2
import dashboard
import service_api
import inventory as inventory_mod
import matrix as matrix_mod
import translate as translate_mod

PORT = int(os.environ.get("PORT", "8080"))
KEEPER_PACK_VERSION = "v2"

SESSION_COOKIE = "keeper_session"
SESSION_TTL = 12 * 3600  # 12h browser sessions, in-memory: restart = re-login
_SESSION_LOCK = threading.RLock()  # only short session dictionary operations

# Assignable in tests to stub upstream providers (no live calls in suite).
urlopen = urllib.request.urlopen

# Hook for model inventory; tests stub server.enumerate_inventory.
enumerate_inventory = inventory_mod.get_inventory

ANTHROPIC_VERSION = "2023-06-01"

# CLI identity for opencode-zen upstream (2026-09-20: keeper relayed bare
# bearer-only requests and the vendor gated them 429; pi-direct with full
# CLI identity 200s on identical keys — see docs/pi-zen-triage.md).
# Forward client-supplied values first; originate sane defaults otherwise
# (same pattern as pi-opencode-direct). Zen routes only — never stamped
# on other providers' traffic.
ZEN_PROVIDER = "opencode-zen"
ZEN_CLI_UA = ("opencode/1.18.31 ai-sdk/provider-utils/4.0.23 "
              "runtime/bun/1.3.14")
ZEN_FWD_HEADERS = ("x-opencode-client", "x-opencode-project",
                     "x-opencode-session", "x-opencode-request",
                     "x-client-request-id", "user-agent")
_ZEN_ID_ALPHABET = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    "abcdefghijklmnopqrstuvwxyz0123456789")


def _zen_rand(prefix):
    return prefix + "".join(
        secrets.choice(_ZEN_ID_ALPHABET) for _ in range(24))


def zen_identity(in_headers):
    """Upstream identity headers for zen routes: passthrough wins."""
    lowered = {str(k).lower(): v for k, v in (in_headers or {}).items()}
    out = {}
    for name in ZEN_FWD_HEADERS:
        if name in lowered and lowered[name]:
            out[name if name != "user-agent" else "User-Agent"] = \
                lowered[name]
    out.setdefault("x-opencode-client", "cli")
    out.setdefault("x-opencode-project", "global")
    out.setdefault("x-opencode-session", _zen_rand("ses_"))
    out.setdefault("x-opencode-request", _zen_rand("msg_"))
    out.setdefault("User-Agent", ZEN_CLI_UA)
    return out
FEEDBACK_REQUIRED = ("provider", "model", "errorClass", "httpStatus",
                     "keeperPackVersion")
FEEDBACK_ERROR_CLASSES = {"auth", "upstream_5xx", "unknown", "limited",
                          "misconfigured", "denied", "timeout"}
GUIDE_WHOS = ("curl", "pi", "opencode")


def require_token(token):
    if not token:
        sys.stderr.write("FATAL: KEEPER_TOKEN unset — refusing to serve\n")
        raise SystemExit(1)
    return token


def load_seed(seed_file):
    """Seed routes from SEED_FILE JSON (fixtures in tests, Bao exports live)."""
    if not seed_file:
        return {"routes": []}
    with open(seed_file, encoding="utf-8") as fh:
        data = json.load(fh)
    routes = data.get("routes", []) if isinstance(data, dict) else []
    return {"routes": [r for r in routes if isinstance(r, dict)]}


def make_state(token, seed=None, feedback_log=None, aa_cache=None,
               aa_api_key=None):
    """In-memory server state; tests build this directly from fixtures."""
    return {
        "token": token,
        "routes": (seed or {}).get("routes", []),
        "feedback_log": feedback_log or os.environ.get(
            "FEEDBACK_LOG", "feedback.jsonl"),
        "aa_cache": aa_cache or os.environ.get("AA_CACHE", "aa-cache.json"),
        "aa_api_key": aa_api_key or os.environ.get(
            "ARTIFICIALANALYSIS_API_KEY", ""),
        "aa_scores": {},
        "aa_stale": False,
        "probe": {},  # connection_id -> state (feedback flips to suspect)
        "probe_detail": {},  # connection_id -> probe_route result (L1/L2)
        "matrix_cache": None,
        "sessions": {},  # sha256(raw cookie) -> expiry epoch (GET-only login)
    }


def connection_id(route):
    return str(route.get("connection_id") or
               (route.get("provider", "") + "/" + route.get("model", "")))


def find_route(state, model):
    """First route for a model, proven-healthy connections first.
    Health (live probe state) outranks seed order: ok beats
    pending/unknown beats dead — a dead key never shadows a proven one
    just because it was seeded earlier."""
    cands = [r for r in state["routes"] if r.get("model") == model]
    if not cands:
        return None
    probe = state.get("probe") or {}
    rank = {"ok": 0, "limited": 1, "misconfigured": 1,
            "suspect": 2, "unknown": 3}

    def sort_key(pair):
        i, r = pair
        # Unprobed sorts with unknown (3); down (or anything
        # unexpected) sinks last at 4.
        return (rank.get(probe.get(connection_id(r), "unknown"), 4), i)

    return sorted(enumerate(cands), key=sort_key)[0][1]


def pack_path(provider, model):
    """Standalone pack identity: infinity/<provider>/<model>."""
    return "infinity/%s/%s" % (provider or "unknown", model or "unknown")


def freeze(state, inventory=None):
    """Frozen packs snapshot: values for live credentials, signin steps
    otherwise. Values only ever go to bearer-authed callers (see route).
    One standalone pack per model; inventory-only models get signin packs."""
    packs = []
    seen = set()
    for route in state["routes"]:
        provider = route.get("provider", "")
        model = route.get("model", "")
        member = {
            "provider": provider,
            "model": model,
            "base_url": route.get("base_url", ""),
            "env_var": route.get("env_var", ""),
            "path": pack_path(provider, model),
        }
        if route.get("api_key"):
            member["credential"] = {"type": "bearer",
                                    "value": route["api_key"]}
        else:
            member["signin"] = {"steps": [
                "export %s=<your-key>" % (route.get("env_var")
                                          or "PROVIDER_API_KEY"),
                "re-mint via your provider dashboard, then retry",
            ]}
        packs.append(member)
        seen.add((provider, model))
    for provider, models in (inventory or {}).items():
        for model in models:
            if (provider, model) in seen:
                continue
            seen.add((provider, model))
            packs.append({
                "provider": provider,
                "model": model,
                "base_url": "",
                "env_var": "",
                "path": pack_path(provider, model),
                "signin": {"steps": [
                    "seed a route for %s/%s, then re-mint via your "
                    "provider dashboard" % (provider, model),
                ]},
            })
    return {"keeperPackVersion": KEEPER_PACK_VERSION, "verification": "unverified_raw_configuration", "packs": packs}


def etag_for(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def json_resp(code, doc, extra=()):
    body = json.dumps(doc).encode()
    return code, body, [("Content-Type", "application/json")] + list(extra)


def text_resp(code, text, ctype="text/plain"):
    return code, text.encode(), [("Content-Type", ctype)]


def _authed(headers, token):
    auth = ""
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value
    return auth == "Bearer " + token


def _session_raw(headers):
    for key, value in headers.items():
        if key.lower() != "cookie":
            continue
        for part in str(value).split(";"):
            name, _, val = part.strip().partition("=")
            if name.strip() == SESSION_COOKIE and val.strip():
                return val.strip()
    return ""


def _valid_session(state, raw):
    if not raw or state is None:
        return False
    now = time.time()
    with _SESSION_LOCK:
        sessions = state.setdefault("sessions", {})
        for key in [k for k, exp in sessions.items() if exp <= now]:
            sessions.pop(key, None)
        return sessions.get(hashlib.sha256(raw.encode()).hexdigest(), 0) > now


def _set_session_cookie(raw):
    return ("Set-Cookie",
            "%s=%s; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=%d"
            % (SESSION_COOKIE, raw, SESSION_TTL))


def _clear_session_cookie():
    return ("Set-Cookie",
            "%s=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"
            % SESSION_COOKIE)


def validate_feedback(doc):
    """Returns (missing[], bad_error_class|None)."""
    if not isinstance(doc, dict):
        return list(FEEDBACK_REQUIRED), None
    missing = [f for f in FEEDBACK_REQUIRED if doc.get(f) in (None, "")]
    if missing:
        return missing, None
    if not isinstance(doc.get("errorClass"), str) or doc["errorClass"] not in FEEDBACK_ERROR_CLASSES:
        return [], doc.get("errorClass")
    return [], None


def spool_feedback(state, doc):
    # Legacy diagnostics are not exact v2 feedback. Persist only trusted route
    # identity and bounded classifications, never arbitrary client messages.
    known = next((r for r in state["routes"] if r.get("provider") == doc.get("provider")
                  and r.get("model") == doc.get("model")), None)
    if not known:
        return
    doc = {"provider": known["provider"], "model": known["model"],
           "errorClass": doc.get("errorClass") if doc.get("errorClass") in FEEDBACK_ERROR_CLASSES else "unknown",
           "httpStatus": doc.get("httpStatus") if isinstance(doc.get("httpStatus"), int) and 100 <= doc["httpStatus"] <= 599 else 0,
           "keeperPackVersion": KEEPER_PACK_VERSION}
    line = json.dumps(doc, sort_keys=True) + "\n"
    with open(state["feedback_log"], "a", encoding="utf-8") as fh:
        fh.write(line)
    state["probe"][str(doc.get("provider", "")) + "/" +
                   str(doc.get("model", ""))] = "suspect"


def provider_view(state):
    """Group seed routes by provider for GET /v1/providers."""
    groups = {}
    for route in state["routes"]:
        provider = route.get("provider", "")
        entry = groups.setdefault(provider, {
            "provider": provider,
            "baseURL": route.get("base_url", ""),
            "modelIDs": [],
            "envVar": route.get("env_var", ""),
            "curl": "",
        })
        if route.get("model") and route["model"] not in entry["modelIDs"]:
            entry["modelIDs"].append(route["model"])
    for entry in groups.values():
        first = entry["modelIDs"][:1]
        entry["curl"] = openai_curl(first[0] if first else "")
    return sorted(groups.values(), key=lambda e: e["provider"])


def openai_curl(model):
    return ("curl -s http://localhost:8080/v1/chat/completions "
            "-H \"Authorization: Bearer $KEEPER_TOKEN\" "
            "-H \"Content-Type: application/json\" "
            "-d '{\"model\": \"%s\", \"messages\": "
            "[{\"role\": \"user\", \"content\": \"ping\"}]}'" % model)


def guide_view(state, who):
    if who not in GUIDE_WHOS:
        return None
    models = sorted({r.get("model", "") for r in state["routes"]
                     if r.get("model")})
    header = {"curl": "# copy-paste: one OpenAI curl per model",
              "pi": "# pi provider block: speak OpenAI to the keeper",
              "opencode": "# opencode: speak OpenAI to the keeper"}[who]
    return {"who": who, "header": header,
            "curls": [{"model": m, "curl": openai_curl(m)} for m in models]}


def call_upstream(route, path, payload, extra_headers=None, timeout=30):
    """(status, body_text) against the provider; tests stub urlopen."""
    raw = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + route.get("api_key", "")}
    headers.update(extra_headers or {})
    req = urllib.request.Request(route["base_url"].rstrip("/") + path,
                                 data=raw, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as res:
            return res.status, res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        try:
            body = err.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return err.code, body
    except Exception as exc:
        return None, "connect-fail: %s" % exc


def openai_error(message, code="upstream_error", http_status=502):
    return http_status, {"error": {"message": message, "type": code,
                                   "code": code}}


def chat_completions(state, req, fwd_headers=None):
    """OpenAI-out chat over either upstream wire. Returns (code, doc|None,
    sse_bytes|None)."""
    if not isinstance(req, dict) or not req.get("model"):
        return openai_error("missing model", "invalid_request", 400)[:2] + (None,)
    route = find_route(state, req["model"])
    if route is None:
        return openai_error("unknown model: %s" % req["model"],
                            "model_not_found", 404)[:2] + (None,)
    wire = route.get("wire", "openai")
    if wire == "anthropic":
        upstream = translate_mod.openai_to_anthropic(
            dict(req, stream=False))
        code, body = call_upstream(
            route, "/v1/messages", upstream,
            {"x-api-key": route.get("api_key", ""),
             "anthropic-version": ANTHROPIC_VERSION})
        if code != 200:
            try:
                err = translate_mod.anthropic_error_to_openai(
                    json.loads(body or "{}"), code or 502)
            except Exception:
                err = {"error": {"message": (body or "")[:200],
                                 "type": "upstream_error",
                                 "code": "upstream_error"}}
            return (code or 502), err, None
        try:
            doc = translate_mod.anthropic_to_openai(
                json.loads(body), req["model"])
        except Exception as exc:
            return openai_error("bad upstream body: %s" % exc)[:2] + (None,)
    elif wire == "openai":
        extra = None
        if route.get("provider") == ZEN_PROVIDER:
            extra = zen_identity(fwd_headers)
        code, body = call_upstream(
            route, "/chat/completions", dict(req, stream=False),
            extra_headers=extra)
        if code != 200:
            try:
                doc = json.loads(body or "{}")
                if not isinstance(doc, dict) or "error" not in doc:
                    raise ValueError("not an error doc")
            except Exception:
                doc = {"error": {"message": (body or "")[:200],
                                 "type": "upstream_error",
                                 "code": "upstream_error"}}
            return (code or 502), doc, None
        try:
            doc = json.loads(body)
        except Exception as exc:
            return openai_error("bad upstream body: %s" % exc)[:2] + (None,)
    else:
        return openai_error("unknown wire: %r" % (wire,),
                            "misconfigured", 502)[:2] + (None,)
    if req.get("stream"):
        return 200, None, sse_from_completion(doc, req["model"])
    return 200, doc, None


def sse_from_completion(doc, model):
    """Synthesize OpenAI SSE from one completion doc: content/tool deltas,
    then one finish_reason, then [DONE]. (Upstream is called non-streaming;
    v2 scope — wire stays OpenAI either way.)"""
    lines = []
    try:
        msg = doc["choices"][0]["message"]
        finish = doc["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError):
        msg, finish = {"content": ""}, "stop"
    delta = {}
    if msg.get("content"):
        delta["content"] = msg["content"]
    for i, tc in enumerate(msg.get("tool_calls") or []):
        delta.setdefault("tool_calls", []).append({
            "index": i, "id": tc.get("id"), "type": "function",
            "function": tc.get("function", {})})
    lines.append("data: " + json.dumps({
        "id": doc.get("id", ""), "object": "chat.completion.chunk",
        "created": 0, "model": model,
        "choices": [{"index": 0, "delta": delta,
                     "finish_reason": None}]}))
    lines.append("data: " + json.dumps({
        "id": doc.get("id", ""), "object": "chat.completion.chunk",
        "created": 0, "model": model,
        "choices": [{"index": 0, "delta": {},
                     "finish_reason": finish or "stop"}]}))
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def models_view(state):
    data = [{"id": r.get("model", ""), "object": "model",
             "owned_by": r.get("provider", "")}
            for r in state["routes"] if r.get("model")]
    return {"object": "list", "data": sorted(data, key=lambda m: m["id"])}


def route_view(state, model):
    route = find_route(state, model)
    if route is None:
        return None
    return {"model": model, "verification": "unverified_raw_configuration", "baseURL": route.get("base_url", ""),
            "api": "openai",
            "auth": {"scheme": "bearer",
                     "value": route.get("api_key", "")},
            "features": ["chat", "stream", "tools"],
            "keeperPackVersion": KEEPER_PACK_VERSION}


def seed_connections(state):
    conns = []
    for route in state["routes"]:
        conns.append({
            "id": connection_id(route),
            "provider": route.get("provider", ""),
            "model": route.get("model", ""),
            "email": route.get("owner", ""),
            "name": route.get("name", "") or route.get("model", ""),
            "isActive": route.get("active", True),
        })
    return conns


def ensure_aa(state, refresh=False):
    """Tiebreak scores only; failure keeps last-good with stale=True."""
    if not state["aa_api_key"]:
        return
    if state["aa_scores"] and not refresh:
        return
    scores, stale = aa.fetch_snapshot(state["aa_api_key"], state["aa_cache"])
    state["aa_scores"] = scores
    state["aa_stale"] = stale


def matrix_view(state, refresh=False):
    if "availability" in state:
        from legacy_view import matrix
        return matrix(state)
    ensure_aa(state, refresh)
    if state["matrix_cache"] is not None and not refresh:
        return state["matrix_cache"]
    inv = enumerate_inventory(state["routes"], refresh)
    doc = matrix_mod.build_matrix(seed_connections(state), state["probe"],
                                  state["aa_scores"],
                                  state.get("probe_detail", {}),
                                  inventory=inv)
    doc["aa_stale"] = state["aa_stale"]
    doc["keeperPackVersion"] = KEEPER_PACK_VERSION
    state["matrix_cache"] = doc
    return doc


def accounts_view(state):
    doc = matrix_view(state)
    return {"emails": doc["emails"],
            "unassigned_count": len(doc["diagnostics"]["unassigned"]),
            "keeperPackVersion": KEEPER_PACK_VERSION}


def prom_esc(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def probe_epoch(when):
    try:
        return int(datetime.fromisoformat(
            str(when).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def metrics_view(state):
    """Prometheus text: divergent + down gauges + per-connection probe timestamp.
    Only connections with a recorded dual verdict get series (L2 runs on
    demand, so 'no series' means 'never dual-probed', not 'fine')."""
    lines = [
        "# HELP keeper_route_divergent L1 curl fails while L2 opencode CLI passes.",
        "# TYPE keeper_route_divergent gauge",
        "# HELP keeper_route_down Both legs fail (L1 non-ok and L2 fail).",
        "# TYPE keeper_route_down gauge",
        "# HELP keeper_probe_checked_at_seconds Unix time of last dual probe.",
        "# TYPE keeper_probe_checked_at_seconds gauge",
        "# HELP keeper_keyqueue_mismatch zenCLI-vs-opencode verdict disagreement per pool key (M4 alert source).",
        "# TYPE keeper_keyqueue_mismatch gauge",
        "# HELP keeper_keyqueue_state Pool key state as separate 0/1 series (label state).",
        "# TYPE keeper_keyqueue_state gauge",
        "# HELP keeper_keyqueue_generated_at_seconds Unix time the pool ledger was rendered.",
        "# TYPE keeper_keyqueue_generated_at_seconds gauge",
    ]
    for k in keyqueue_view(state).get("keys", []):
        name = prom_esc(k.get("name", ""))
        lines.append('keeper_keyqueue_mismatch{key="%s"} %d'
                     % (name, 1 if k.get("mismatch") else 0))
        for s in ("pending", "testing", "ok", "dead"):
            lines.append('keeper_keyqueue_state{key="%s",state="%s"} %d'
                         % (name, s, 1 if k.get("state") == s else 0))
    gen = keyqueue_view(state).get("generated_at")
    ts = probe_epoch(gen or "")
    if ts is not None:
        lines.append("keeper_keyqueue_generated_at_seconds %d" % ts)
    for cid in sorted((state.get("probe_detail") or {})):
        det = state["probe_detail"][cid] or {}
        verdict = matrix_mod.dual_verdict(det)
        labels = 'provider="%s",model="%s",connection="%s"' % (
            prom_esc(det.get("provider", "")),
            prom_esc(det.get("model", "")), prom_esc(cid))
        lines.append("keeper_route_divergent{%s} %d"
                     % (labels, 1 if verdict["divergent"] else 0))
        lines.append("keeper_route_down{%s} %d"
                     % (labels, 1 if verdict["state"] == "down" else 0))
        ts = probe_epoch(det.get("checked_at", ""))
        if ts is not None:
            lines.append("keeper_probe_checked_at_seconds{%s} %d"
                         % (labels, ts))
    try:
        with state.get("_http_lock", threading.Lock()):
            http_table = dict(state.get("_http") or {})
    except Exception:
        http_table = {}
    if http_table:
        lines += [
            "# HELP keeper_http_responses_total HTTP responses by normalized route and status.",
            "# TYPE keeper_http_responses_total counter",
            "# HELP keeper_http_latency_ms_sum Total HTTP latency ms by route.",
            "# TYPE keeper_http_latency_ms_sum counter",
            "# HELP keeper_http_latency_ms_count HTTP response count by route.",
            "# TYPE keeper_http_latency_ms_count counter",
        ]
        agg = {}
        for key in sorted(http_table):
            try:
                route_cls, code = key.split("|", 1)
                count, total = http_table[key]
            except (ValueError, TypeError):
                continue
            lines.append('keeper_http_responses_total{route="%s",code="%s"} %d'
                         % (prom_esc(route_cls), prom_esc(code), count))
            row = agg.setdefault(route_cls, [0, 0])
            row[0] += count
            row[1] += total
        for route_cls in sorted(agg):
            count, total = agg[route_cls]
            lines.append('keeper_http_latency_ms_sum{route="%s"} %d'
                         % (prom_esc(route_cls), total))
            lines.append('keeper_http_latency_ms_count{route="%s"} %d'
                         % (prom_esc(route_cls), count))
    lines += [
        "# HELP keeper_process_rss_bytes Resident memory of the server process.",
        "# TYPE keeper_process_rss_bytes gauge",
        "# HELP keeper_process_cpu_seconds_total User+system CPU time of the server process.",
        "# TYPE keeper_process_cpu_seconds_total counter",
    ]
    lines.extend(process_metrics_lines())
    try:
        import usage_metrics
        lines.extend(usage_metrics.lines(state))
    except Exception:
        lines.append("# keeper usage metrics unavailable")
    return "\n".join(lines) + "\n"


def process_metrics_lines():
    """Stdlib-only process stats (no psutil). ru_maxrss is KiB on Linux
    (production) but bytes on macOS (dev) — normalize by platform."""
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss = ru.ru_maxrss * (1024 if sys.platform.startswith("linux") else 1)
        cpu = ru.ru_utime + ru.ru_stime
    except Exception:
        return []
    return ["keeper_process_rss_bytes %d" % rss,
            "keeper_process_cpu_seconds_total %.2f" % cpu]


def health_view(state):
    if "availability" in state:
        connections = state["availability"].connections()
        return {"ok": not bool(state.get("worker_error")), "keeperPackVersion": KEEPER_PACK_VERSION,
                "routes": {c["id"]: c["state"] for c in connections},
                "route_protocols": {c["id"]: c["protocol"] for c in connections},
                "evidence": "exact_transport" if any(c["protocol"] == "zencli" for c in connections) else "exact_direct_api"}
    return {"ok": True, "keeperPackVersion": KEEPER_PACK_VERSION,
            "routes": dict(state["probe"])}


def page_login():
    """Public login form: token goes in a fetch Authorization header (POST
    body path), never in the URL. On 200 the session cookie is set."""
    return ("<html><head><meta charset=\"utf-8\"><title>keeper login</title></head><body>"
            "<h1>keeper login</h1>"
            "<form id=\"f\"><input id=\"t\" type=\"password\" "
            "autocomplete=\"off\" placeholder=\"KEEPER_TOKEN\"/>"
            "<button type=\"submit\">sign in</button></form>"
            "<p id=\"e\"></p>"
            "<script>"
            "document.getElementById('f').onsubmit=async(ev)=>{"
            "ev.preventDefault();"
            "const t=document.getElementById('t').value;"
            "const r=await fetch('/api/v1/session',{method:'POST',"
            "headers:{'Authorization':'Bearer '+t}});"
            "if(r.ok){location='/';}else{"
            "document.getElementById('e').textContent='rejected ('+r.status+')';}"
            "};"
            "</script></body></html>")


def _col_probed(doc, col):
    for p in doc["providers"]:
        if p.get("id") == col and "probed" in p:
            return bool(p["probed"])
    return any(row["cells"].get(col) for row in doc["rows"])


def _state_class(state):
    return "st-" + "".join(c if c.isalpha() else "-"
                            for c in str(state).lower())


_STATE_RANK = {"down": 0, "degraded": 0, "suspect": 1, "limited": 2,
               "misconfigured": 2, "unknown": 3, "ok": 4}


def _open_sort_key(doc):
    """Provider-open column order: AA score desc, unscored last, name
    tiebreak. Display-only: the matrix JSON keeps insertion order and
    every column; only the opened view sorts + filters (see data-anyok).
    AA scores ride on cell entries, so the key derives from the doc."""
    scores, anyok = {}, {}
    for row in doc["rows"]:
        for col, entries in row["cells"].items():
            for e in entries:
                s = e.get("aa_score")
                if isinstance(s, (int, float)) and (
                        col not in scores or s > scores[col]):
                    scores[col] = s
                if e.get("state") == "ok":
                    anyok[col] = True

    def key(p):
        col = p["id"]
        aa = scores.get(col)
        return (-(aa if aa is not None else -1.0),
                str(p.get("model") or col))
    return key


def _open_attrs(doc, col):
    """data-c + data-anyok flags the poller + click handler reuse."""
    ok = any(e.get("state") == "ok"
             for row in doc["rows"]
             for e in row["cells"].get(col, []))
    return col, "1" if ok else "0"


def _worst_state(states):
    """Worst of a set of cell states for provider summaries."""
    states = [str(s) for s in states]
    if not states:
        return "unknown"
    return min(states, key=lambda s: _STATE_RANK.get(s, 2))


def keyqueue_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "keyqueue.json")


def keyqueue_view(state=None):
    """Pool ledger for GET /api/v1/key-queue (names only, never keys).
    Baked keyqueue.json overlaid with live ingested rounds (detail.source
    == keyround): POSTing a round immediately moves the queue AND the
    mismatch metric (both read this view, never the file directly)."""
    if state is not None and "availability" in state:
        keys = state["availability"].accounts()["keys"]
        mixed = any(c["protocol"] == "zencli" for k in keys for c in k["connections"])
        return {"generated_at": datetime.now(timezone.utc).isoformat(),
                "evidence": "exact_transport" if mixed else "exact_direct_api", "keys": [
                    {"name": k["reference"], "provider": k["provider"], "owner": k["owner"],
                     "state": "ok" if k["state"] == "working" else k["state"],
                     "working_models": k["working"], "total_models": k["total"],
                     "working_transports": sorted({c["protocol"] for c in k["connections"] if c["state"] == "working"}),
                     "active": bool(k["active"])} for k in keys]}
    try:
        with open(keyqueue_path(), encoding="utf-8") as fh:
            doc = json.load(fh)
        if not (isinstance(doc, dict)
                and isinstance(doc.get("keys"), list)):
            doc = {"generated_at": None, "keys": []}
    except (OSError, ValueError):
        doc = {"generated_at": None, "keys": []}
    if state is not None:
        doc = overlay_keyqueue_live(doc, state.get("probe_detail") or {})
    return doc


def overlay_keyqueue_live(doc, probe_detail):
    """Fold live heartbeat records into a ledger copy. Newer live
    verdicts replace baked fields; dead streak extends, recovery resets."""
    import copy
    from datetime import datetime, timedelta, timezone
    doc = copy.deepcopy(doc)
    by_name = {k.get("name"): k for k in doc.get("keys", [])}
    for _cid, rec in probe_detail.items():
        det = rec.get("detail") or {}
        if det.get("source") != "keyround":
            continue
        name = det.get("key_name")
        entry = by_name.get(name)
        if entry is None:
            continue
        live_ts = rec.get("checked_at", "")
        if live_ts <= (entry.get("checked_at") or ""):
            continue
        down = rec.get("state") == "down"
        live_streak = (rec.get("detail") or {}).get("dead_streak")
        try:
            dead = int(live_streak)
        except (ValueError, TypeError):
            # No live streak (boot seed): extend the baked one once.
            dead = (entry.get("consecutive_dead", 0) + 1) if down else 0
        try:
            base = datetime.strptime(live_ts, "%Y-%m-%dT%H:%M:%SZ")
            base = base.replace(tzinfo=timezone.utc)
            gap = min(2 ** dead, 24) if dead else 1
            nxt = (base + timedelta(hours=gap)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            nxt = entry.get("next_test")
        entry.update({
            "state": "dead" if down else "ok",
            "zencli": det.get("zencli"),
            "opencode": det.get("opencode"),
            "mismatch": bool(det.get("mismatch")),
            "retry_hint_secs": det.get("retry_hint_secs"),
            "models_ok": det.get("models_ok"),
            "models_total": det.get("models_total"),
            "models": det.get("models"),
            "checked_at": live_ts, "consecutive_dead": dead,
            "next_test": nxt})
    return doc


def model_sublist(k):
    """Per-model ok/fail under a key row: WHICH models work, not just
    how many. Short model names keep rows readable."""
    models = k.get("models") or {}
    if not models:
        return ""
    lis = []
    for m in sorted(models):
        ok = (models[m].get("zencli") or {}).get("ok")
        short = html.escape(m.replace("-free", "").replace(
            "-contributor", "").replace("ling-3.0-flash-fin", "ling"))
        lis.append('<li data-m="%s">%s \u2014 %s</li>'
                   % (html.escape(m), short, "ok" if ok else "fail"))
    return "<ul>%s</ul>" % "".join(lis)


def keyqueue_items(doc):
    """Server-rendered pool list for the matrix page section: state +
both verdicts + next test (auditor fix: no verdict-less rows)."""
    rows = []
    for k in doc.get("keys", []):
        name = html.escape(k.get("name", "?"))
        state = html.escape(k.get("state", "pending"))
        zen = k.get("zencli") or {}
        op = k.get("opencode")
        bits = "zencli=%s" % ("ok" if zen.get("ok") else
                                ("fail" if "ok" in zen else "—"))
        bits += " opencode=%s" % (
            "ok" if (op or {}).get("ok") else
            ("fail" if op else "—")) if op is not None else " opencode=—"
        if k.get("mismatch"):
            bits += " MISMATCH"
        if k.get("models_total"):
            bits += " models %s/%s" % (html.escape(str(k.get(
                "models_ok", "?"))), html.escape(str(
                    k["models_total"])))
        if k.get("retry_hint_secs") is not None:
            bits += " retry~%ss" % html.escape(
                str(k["retry_hint_secs"]))
        nxt = (" next=%s" % html.escape(k["next_test"])
               if k.get("next_test") else "")
        chk = ((" \u2014 " + html.escape(k.get("checked_at") or ""))
               if k.get("checked_at") else "")
        rows.append('<li data-q="%s">%s \u2014 %s \u2014 %s%s%s%s</li>'
                    % (name, name, state, html.escape(bits), chk,
                       nxt, model_sublist(k)))
    return "".join(rows) or "<li>no pool ledger</li>"


def page_index(state):
    """Server-rendered matrix + just-in-time poller.

    The initial table is rendered here (works without JS); the embedded
    script re-reads the SAME agent endpoint browsers would use anyway
    (GET /api/v1/matrix?refresh=1) every 30s and re-renders cells in
    place. A failed fetch surfaces a stale banner — never silent old data.
    DOM is built with textContent (no innerHTML) so route names cannot
    inject markup."""
    doc = matrix_view(state)
    keymap = _zen_keymap(state)
    tuples = _zen_tuples(doc)
    perkey = _zen_perkey(doc, keymap)
    tuple_items = "".join(
        '<li data-t="%s|%s">%s \u2014 %s \u2014 %s \u2014 %s</li>'
        % (html.escape(c), html.escape(m), html.escape(c),
           html.escape(m), html.escape(p), html.escape(t or ""))
        for c, m, p, t in tuples) or "<li>none right now</li>"
    perkey_secs = []
    for tag in sorted(perkey):
        pairs = perkey[tag]
        owners = sorted(set(email for email, _e in pairs))
        lis = "".join(
            '<li>%s \u2014 %s (%s/%s) \u2014 %s</li>'
            % (html.escape(e.get("model", "?")),
               html.escape(e.get("state", "unknown")),
               html.escape(str(e.get("l1", "?"))),
               html.escape(str(e.get("l2", "?"))),
               html.escape(e.get("checked_at", "") or ""))
            for _email, e in pairs)
        perkey_secs.append(
            '<h3 data-k="%s">%s <small>(%s)</small></h3>'
            '<p class="verdict" data-k="%s">%s</p><ul data-k="%s">%s</ul>'
            % (html.escape(tag), html.escape(tag),
               html.escape(", ".join(owners)), html.escape(tag),
               html.escape(_zen_verdict(tag, pairs)), html.escape(tag),
               lis))
    keymap_js = json.dumps(keymap).replace("</", "<\\/")
    col_ids = [p["id"] for p in doc["providers"]]
    probed = {c: _col_probed(doc, c) for c in col_ids}
    groups = []
    for p in doc["providers"]:
        if p.get("provider") not in groups:
            groups.append(p.get("provider"))
    cols_of = {}
    for g in groups:
        members = [p for p in doc["providers"]
                   if p.get("provider") == g]
        cols_of[g] = sorted(members, key=_open_sort_key(doc))

    def _prov_states(prov):
        states = []
        for row in doc["rows"]:
            for p in cols_of.get(prov, []):
                for e in row["cells"].get(p["id"], []):
                    states.append(e.get("state", "unknown"))
        return states

    prov_head = []
    for g in groups:
        worst = _worst_state(_prov_states(g))
        prov_head.append(
            '<th class="prov" data-p="%s" title="click to expand">'
            '<span class="st %s">\u25cf</span> %s</th>'
            % (html.escape(g or ""), _state_class(worst),
               html.escape(g or "unknown")))
    mod_head = []
    for g in groups:
        for p in cols_of[g]:
            label = p.get("model") or p["id"]
            col, anyok = _open_attrs(doc, p["id"])
            mod_head.append(
                '<th class="mod" data-p="%s" data-c="%s" '
                'data-anyok="%s" hidden>%s</th>'
                % (html.escape(g or ""), html.escape(col),
                   anyok, html.escape(label)))
    rows = []
    for row in doc["rows"]:
        cells = []
        for g in groups:
            states = []
            for p in cols_of[g]:
                for e in row["cells"].get(p["id"], []):
                    states.append(e.get("state", "unknown"))
            worst = _worst_state(states) if states else "unknown"
            if states:
                cells.append(
                    '<td class="provsum" data-p="%s">'
                    '<span class="st %s">\u25cf %s</span></td>'
                    % (html.escape(g or ""), _state_class(worst),
                       html.escape(worst)))
            else:
                cells.append(
                    '<td class="provsum unprobed" data-p="%s" '
                    'title="unprobed">\u2014</td>'
                    % html.escape(g or ""))
            for p in cols_of[g]:
                entries = row["cells"].get(p["id"], [])
                col, anyok = _open_attrs(doc, p["id"])
                if entries:
                    cells.append(
                        '<td class="mod" data-p="%s" data-c="%s" '
                        'data-anyok="%s" hidden>%s</td>'
                        % (html.escape(g or ""), html.escape(col),
                           anyok, ", ".join(
                            _cell_html(e) for e in entries)))
                elif probed[p["id"]]:
                    cells.append(
                        '<td class="mod" data-p="%s" data-c="%s" '
                        'data-anyok="%s" hidden>\u2014</td>'
                        % (html.escape(g or ""), html.escape(col),
                           anyok))
                else:
                    cells.append(
                        '<td class="mod unprobed" data-p="%s" '
                        'data-c="%s" data-anyok="%s" hidden '
                        'title="unprobed">\u2014</td>'
                        % (html.escape(g or ""), html.escape(col),
                           anyok))
        rows.append("<tr><td>%s</td>%s</tr>" % (html.escape(row["email"]),
                                               "".join(cells)))
    unassigned = "".join("<li>%s</li>" % html.escape(
        "%s (%s)" % (u.get("name", "?"), u.get("provider", "?")))
        for u in doc["diagnostics"]["unassigned"])
    return ("<html><head><meta charset=\"utf-8\"><title>keeper matrix</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:2em}"
            "table{border-collapse:collapse}"
            "td,th{border:1px solid #ccc;padding:.3em .6em;text-align:left}"
            ".div{color:#fff;background:#c0392b;border-radius:3px;"
            "padding:0 .4em;font-size:.8em}"
            ".st-ok{color:#1e7e34}.st-suspect{color:#b26a00}"
            ".st-down,.st-degraded{color:#c0392b;font-weight:bold}"
            ".st-unknown{color:#777}"
            "td.unprobed{background:#f2f2f2;color:#aaa}"
            ".legend{font-size:.85em;color:#555}"
            "#stale{display:none;background:#f39c12;color:#000;"
            "padding:.5em;margin-bottom:1em}"
            "small{color:#666}th.prov{cursor:pointer;white-space:nowrap}"
            ".mod[hidden]{display:none}</style></head><body>"
            "<h1>keeper matrix</h1>"
            "<h2>working tuples (key \u2014 model \u2014 pi path)</h2>"
            "<ul id=\"tuples\">%s</ul>"
            "<p class=\"legend\">keyed opencode-zen-free path "
            "(quota-aware, not live in keeper): %s</p>"
            "<p id=\"stale\"></p>"
            "<p id=\"aastale\"%s>AA scores stale — open-provider "
            "order may lag</p>"
            "<table id=\"tbl\" data-cols=\"%s\"><thead>"
            "<tr><th>owner</th>%s</tr><tr id=\"modhead\"><th></th>%s</tr>"
            "</thead>"
            "<tbody id=\"cells\">%s</tbody></table>"
            "<p><small id=\"updated\"></small> "
            "<button id=\"lo\">log out</button></p>"
            "<p class=\"legend\">green ok · amber suspect · red down · "
            "gray unknown · <span class=\"div\">DIVERGENT</span> split · "
            "gray — unprobed · opening a provider shows only ok models, "
            "best AA score first</p>"
            "<h2>diagnostics.unassigned</h2><ul id=\"unassigned\">%s</ul>"
            "<h2>per key (zen)</h2><div id=\"perkey\">%s</div>"
            "<h2>key queue (pool heartbeat)</h2>"
            "<div id=\"keyqueue\"><ul>%s</ul></div>"
            "<script>var KEYMAP=%s;</script>"
            "<script>"
            "const T=document.getElementById('cells'),"
            "S=document.getElementById('stale'),"
            "U=document.getElementById('updated'),"
            "N=document.getElementById('unassigned');"
            "document.getElementById('lo').onclick=async()=>{"
            "await fetch('/api/v1/session/logout',{method:'POST'});"
            "location='/login';};"
            "const EXP=new Set();"
            "document.getElementById('tbl').addEventListener('click',ev=>{"
            "const th=ev.target.closest('th.prov');if(!th)return;"
            "const p=th.dataset.p,open=!EXP.has(p);"
            "if(open)EXP.add(p);else EXP.delete(p);"
            "document.querySelectorAll('#tbl .mod').forEach(el=>{"
            "if(el.dataset.p!==p)return;"
            "el.hidden=open?el.dataset.anyok!=='1':true;});});"
            "function cell(e){const s=document.createElement('span');"
            "s.className='st st-'+String(e.state).replace(/[^a-z]/g,'-');"
            "s.textContent=e.name+' ('+e.state+')';"
            "if(e.divergent){const b=document.createElement('span');"
            "b.className='div';b.textContent='DIVERGENT';"
            "s.appendChild(document.createTextNode(' '));s.appendChild(b);}"
            "if(e.checked_at){const t=document.createElement('small');"
            "t.textContent=' '+e.checked_at;s.appendChild(t);}"
            "return s;}"
            "async function poll(){"
            "try{const r=await fetch('/api/v1/matrix?refresh=1');"
            "if(!r.ok)throw new Error(r.status);"
            "const d=await r.json();"
            "const groups=[];for(const p of d.providers)"
            "{if(groups.indexOf(p.provider)<0)groups.push(p.provider);}"
            "const rank={down:0,degraded:0,suspect:1,limited:2,"
            "misconfigured:2,unknown:3,ok:4};"
            "const worst=ss=>{ss=ss.map(String);"
            "return ss.length?ss.reduce((a,b)=>rank[a]<rank[b]?a:b):"
            "'unknown';};"
            "const cls=s=>'st st-'+String(s).replace(/[^a-z]/g,'-');"
            "const AAS={},OKC={};"
            "d.rows.forEach(row=>{for(const id in (row.cells||{}))"
            "for(const e of (row.cells[id]||[])){"
            "if(e.aa_score!=null)AAS[id]=Math.max("
            "AAS[id]==null?-1:AAS[id],e.aa_score);"
            "if(e.state==='ok')OKC[id]=1;}});"
            "const colKey=q=>[AAS[q.id]==null?-1:AAS[q.id],"
            "String(q.model||q.id)];"
            "const colOrd=(a,b)=>(colKey(b)[0]-colKey(a)[0])||"
            "(colKey(a)[1]<colKey(b)[1]?-1:1);"
            "const MH=document.getElementById('modhead');"
            "MH.replaceChildren(...(()=>{const out=["
            "document.createElement('th')];"
            "for(const g of groups){d.providers.filter("
            "p=>p.provider===g).sort(colOrd).forEach(q=>{"
            "const h=document.createElement('th');h.className='mod';"
            "h.dataset.p=g;h.dataset.c=q.id;"
            "h.dataset.anyok=OKC[q.id]?'1':'0';"
            "h.hidden=!(EXP.has(g)&&OKC[q.id]);"
            "h.textContent=q.model||q.id;out.push(h);});}"
            "return out;})());"
            "const init=document.getElementById('tbl').dataset.cols."
            "split(',').sort();"
            "const ids=d.providers.map(p=>p.id).sort();"
            "if(ids.join(',')!==init.join(',')){S.style.display='block';"
            "S.textContent='new models available — reload the page.';return;}"
            "T.replaceChildren(...d.rows.map(row=>{"
            "const tr=document.createElement('tr'),"
            "td=document.createElement('td');"
            "td.textContent=row.email;tr.appendChild(td);"
            "for(const g of groups){"
            "const cols=d.providers.filter(p=>p.provider===g).sort(colOrd),"
            "st=[];"
            "for(const q of cols)"
            "for(const e of (row.cells[q.id]||[]))st.push(e.state);"
            "const w=worst(st),sum=document.createElement('td');"
            "sum.className='provsum'+(st.length?'':' unprobed');"
            "sum.dataset.p=g;"
            "if(st.length){const sp=document.createElement('span');"
            "sp.className=cls(w);sp.textContent='\\u25cf '+w;"
            "sum.appendChild(sp);}"
            "else{sum.title='unprobed';sum.textContent='\\u2014';}"
            "tr.appendChild(sum);"
            "for(const q of cols){const c=document.createElement('td');"
            "c.dataset.p=g;c.dataset.c=q.id;"
            "c.dataset.anyok=OKC[q.id]?'1':'0';"
            "c.hidden=!(EXP.has(g)&&OKC[q.id]);"
            "const es=row.cells[q.id]||[];"
            "if(!es.length){c.textContent='\\u2014';"
            "if(q.probed===false){c.className='mod unprobed';"
            "c.title='unprobed';}else{c.className='mod';}}"
            "else{c.className='mod';"
            "es.forEach((e,i)=>{if(i)c.appendChild("
            "document.createTextNode(', '));c.appendChild(cell(e));});}"
            "tr.appendChild(c);}}return tr;}));"
            "for(const g of groups){"
            "const cols=d.providers.filter(p=>p.provider===g),st=[];"
            "for(const row of d.rows)for(const q of cols)"
            "for(const e of (row.cells[q.id]||[]))st.push(e.state);"
            "const w=worst(st);"
            "document.querySelectorAll('#tbl th.prov').forEach(h=>{"
            "if(h.dataset.p!==g)return;"
            "const sp=h.querySelector('span');"
            "if(sp){sp.className=cls(w);"
            "sp.textContent='\\u25cf '+(st.length?w:g);}});}"
            "N.replaceChildren(...d.diagnostics.unassigned.map(u=>{"
            "const li=document.createElement('li');"
            "li.textContent=u.name+' ('+u.provider+')';return li;}));"
            "if(!d.diagnostics.unassigned.length){const li="
            "document.createElement('li');li.textContent='none';"
            "N.replaceChildren(li);}"
            "S.style.display='none';"
            "rebuildTuples(d);rebuildPerKey(d);"
            "U.textContent='updated '+new Date().toLocaleTimeString();"
            "document.getElementById('aastale').style.display="
            "d.aa_stale?'block':'none';"
            "}catch(e){S.style.display='block';"
            "S.textContent='stale — refresh failed ('+e.message+')';}}"
            "function tuplesOf(d){const out=[];"
            "d.rows.forEach(row=>{for(const id in (row.cells||{}))"
            "for(const e of (row.cells[id]||[])){"
            "const cid=e.connection_id||'';"
            "if(cid.indexOf('zen/')!==0)continue;"
            "if(e.l2==='pass')out.push([cid,e.model||'?',"
            "'CLI',e.checked_at||'']);"
            "if(e.state==='ok')out.push([cid,e.model||'?',"
            "'direct-HTTP',e.checked_at||'']);}});return out;}"
            "function rebuildTuples(d){const T="
            "document.getElementById('tuples');if(!T)return;"
            "T.replaceChildren(...tuplesOf(d).map(t=>{"
            "const li=document.createElement('li');"
            "li.textContent=t[0]+' \u2014 '+t[1]+' \u2014 '+t[2]+"
            "' \u2014 '+t[3];return li;}));"
            "if(!T.children.length){const li="
            "document.createElement('li');"
            "li.textContent='none right now';T.appendChild(li);}}"
            "function verdictOf(k,es){const ps=es.filter("
            "e=>e.l2==='pass').length,oks=es.filter("
            "e=>e.state==='ok').length,latest=es.map("
            "e=>e.checked_at||'').sort().pop()||'';"
            "let v;"
            "if(ps)v='alive \u2014 CLI serves '+ps+'/'+es.length+"
            "' models (checked '+latest+'); Bao: all 10 zen keys "
            "status=active verified 2026-09-19; per-key auth masked "
            "by cluster wall';"
            "else if(oks)v='alive \u2014 direct HTTP ok on '+oks+"
            "' models (checked '+latest+'); Bao: all 10 zen keys "
            "status=active verified 2026-09-19; per-key auth masked "
            "by cluster wall';"
            "else v='no working path right now (checked '+latest+"
            "'); key present in Bao; Bao: all 10 zen keys "
            "status=active verified 2026-09-19; per-key auth masked "
            "by cluster wall';"
            "if(k==='OPENCODE_ZEN_API_KEY'||"
            "k==='OPENCODE_ZEN_API_KEY_PETR')"
            "v+='; keyed chat quota spent as of 2026-09-19 morning; "
            "retired keys answered with fresh quota';"
            "return v;}"
            "function rebuildPerKey(d){const S="
            "document.getElementById('perkey');if(!S)return;"
            "const g={};d.rows.forEach(row=>{"
            "for(const id in (row.cells||{}))"
            "for(const e of (row.cells[id]||[])){"
            "const cid=e.connection_id||'';"
            "if(cid.indexOf('zen/')!==0)continue;"
            "const k=(window.KEYMAP||{})[cid]||cid;"
            "(g[k]=g[k]||[]).push(e);}});"
            "S.replaceChildren(...Object.keys(g).sort().map(k=>{"
            "const f=document.createDocumentFragment();"
            "const h=document.createElement('h3');"
            "h.textContent=k;f.appendChild(h);"
            "const v=document.createElement('p');"
            "v.className='verdict';v.textContent=verdictOf(k,g[k]);"
            "f.appendChild(v);const ul=document.createElement('ul');"
            "g[k].forEach(e=>{const li=document.createElement('li');"
            "li.textContent=(e.model||'?')+' \u2014 '+e.state+' ('+"
            "e.l1+'/'+e.l2+') \u2014 '+(e.checked_at||'');"
            "ul.appendChild(li);});f.appendChild(ul);return f;}));}"
            "setInterval(poll,30000);"
            "</script></body></html>"
            % (tuple_items, html.escape(ZEN_KEYED_NOTE),
               ("" if doc.get("aa_stale") else " style=\"display:none\""),
               ",".join(html.escape(c) for c in col_ids),
               "".join(prov_head), "".join(mod_head),
               "".join(rows), unassigned or "<li>none</li>",
               "".join(perkey_secs), page_queue_section(state),
               keymap_js))


def page_queue_section(state):
    """Standalone key-queue fragment (page section content)."""
    return keyqueue_items(keyqueue_view(state))


def _zen_keymap(state):
    """connection_id -> Bao key name (env_var) for zen routes.
    Rendered into the page (not matrix JSON) so the poller can group
    per-key without changing the JSON shape. Key names are not secrets
    (page_signin already lists env_var names)."""
    out = {}
    for r in state.get("routes", []):
        if r.get("provider") == "opencode-zen" and r.get("connection_id"):
            out[r["connection_id"]] = r.get("env_var", "?")
    return out


# Static, dated Bao knowledge (verified 2026-09-19 morning; keys
# untouched). Live states come from the matrix; these strings never
# pretend to be live. See docs/zen-diagnosis.md + zen-egress-receipts/.
ZEN_KEY_NOTE = ("Bao: all 10 zen keys status=active verified "
                "2026-09-19; per-key auth masked by cluster wall")
ZEN_QUOTA_KEYS = {"OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_API_KEY_PETR"}
ZEN_QUOTA_NOTE = ("keyed chat quota spent as of 2026-09-19 morning; "
                  "retired keys answered with fresh quota")
ZEN_KEYED_NOTE = ("keyed opencode-zen-free path (quota-aware, not live "
                  "in keeper): proven 4s on RETIRED_1 2026-09-19; live "
                  "keys quota-spent; direct HTTP never (FreeTierError)")
# Per-key keyed-chat evidence (measured 2026-09-19 morning; static
# and dated by design — keeper never chats via zen-free itself).
# Maps Bao key name -> models with a proven keyed answer. Live keys are
# quota-spent (see ZEN_QUOTA_KEYS); other pairs are untested, never
# claimed. See x-as-llm-api/docs/zen-egress-receipts/ + pi-infinity-llm
# docs/M2-muse-keyed-proof.txt.
ZEN_KEYED_PROVEN = {
    "OPENCODE_ZEN_RETIRED_1": ["mimo-v2.5-free",
                                  "muse-spark-1.3-contributor-free"],
    "OPENCODE_ZEN_RETIRED_2": ["mimo-v2.5-free"],
    "OPENCODE_ZEN_RETIRED_3": ["mimo-v2.5-free"],
    "OPENCODE_ZEN_RETIRED_4": ["mimo-v2.5-free"],
    "OPENCODE_ZEN_RETIRED_5": ["mimo-v2.5-free"],
    "OPENCODE_ZEN_RETIRED_6": ["mimo-v2.5-free"],
    "OPENCODE_ZEN_RETIRED_7": ["mimo-v2.5-free"],
    "OPENCODE_ZEN_RETIRED_8": ["mimo-v2.5-free"],
}
ZEN_KEYED_DATE = "2026-09-19"
ZEN_PLAIN_NEVER = ("plain completions: never (FreeTierError, vendor "
                   "policy — key tier, not network)")


def _zen_tuples(doc):
    """Working (key-tag, model, pi-path) tuples from live matrix data.
    CLI-usable: any zen entry with l2 == pass. Direct-HTTP: state == ok
    (empty for free zen by vendor policy — shown explicitly, never faked)."""
    out = []
    for row in doc["rows"]:
        for _col, entries in row["cells"].items():
            for e in entries:
                cid = e.get("connection_id", "")
                if not cid.startswith("zen/"):
                    continue
                if e.get("l2") == "pass":
                    out.append((cid, e.get("model", "?"), "CLI",
                                e.get("checked_at", "")))
                if e.get("state") == "ok":
                    out.append((cid, e.get("model", "?"), "direct-HTTP",
                                e.get("checked_at", "")))
    return sorted(set(out))


def _zen_perkey(doc, keymap):
    """Group zen entries by Bao key name -> {tag: [entries]}."""
    groups = {}
    for row in doc["rows"]:
        for _col, entries in row["cells"].items():
            for e in entries:
                cid = e.get("connection_id", "")
                if not cid.startswith("zen/"):
                    continue
                tag = keymap.get(cid, cid)
                groups.setdefault(tag, []).append(
                    (row.get("email", "?"), e))
    return groups


def _zen_verdict(tag, pairs):
    """Alive/quota/no-path verdict for one key's entries + evidence."""
    entries = [e for _, e in pairs]
    passed = [e for e in entries if e.get("l2") == "pass"]
    oks = [e for e in entries if e.get("state") == "ok"]
    latest = max([e.get("checked_at", "") for e in entries] or [""])
    if passed:
        v = ("alive — CLI serves %d/%d models (checked %s); %s"
             % (len(passed), len(entries), latest, ZEN_KEY_NOTE))
    elif oks:
        v = ("alive — direct HTTP ok on %d models (checked %s); %s"
             % (len(oks), latest, ZEN_KEY_NOTE))
    else:
        v = ("no working path right now (checked %s); key present in "
             "Bao; %s" % (latest, ZEN_KEY_NOTE))
    if tag in ZEN_QUOTA_KEYS:
        v += "; " + ZEN_QUOTA_NOTE
    return v


def _cell_html(entry):
    out = '<span class="st %s">%s</span>' % (
        _state_class(entry["state"]),
        html.escape("%s (%s)" % (entry["name"], entry["state"])))
    if entry.get("divergent"):
        out += ' <span class="div">DIVERGENT</span>'
    if entry.get("checked_at"):
        out += " <small>%s</small>" % html.escape(entry["checked_at"])
    return out


def page_guides(state):
    cards = []
    for who in GUIDE_WHOS:
        view = guide_view(state, who)
        curls = "\n".join(html.escape(c["curl"]) for c in view["curls"])
        cards.append("<h2>%s</h2><pre>%s\n%s</pre>"
                     % (html.escape(who), html.escape(view["header"]), curls))
    return ("<html><head><meta charset=\"utf-8\"><title>guides</title></head><body>"
            "<h1>guides</h1>%s</body></html>" % "".join(cards))


def page_signin(state):
    steps = []
    for route in state["routes"]:
        if not route.get("api_key"):
            steps.append("<li>%s: export %s, then re-mint via your "
                         "provider dashboard</li>"
                         % (html.escape(route.get("model", "?")),
                            html.escape(route.get("env_var", "?"))))
    return ("<html><head><meta charset=\"utf-8\"><title>signin</title></head><body>"
            "<h1>signin: re-mint steps</h1><ul>%s</ul></body></html>"
            % ("".join(steps) or "<li>all routes have live credentials</li>"))


def page_report(state):
    options = "".join("<option>%s</option>" % html.escape(
        "%s/%s:%s" % (r.get("provider", ""), r.get("model", ""),
                      state["probe"].get(connection_id(r), "unknown")))
        for r in state["routes"])
    return ("<html><head><meta charset=\"utf-8\"><title>report</title></head><body>"
            "<h1>report a route problem</h1>"
            "<p>live route state is shown per option</p>"
            "<form method=\"post\" action=\"/feedback\">"
            "<select name=\"route\">%s</select>"
            "<input name=\"errorClass\" placeholder=\"errorClass\"/>"
            "<input name=\"httpStatus\" placeholder=\"httpStatus\"/>"
            "<button>send</button></form></body></html>" % options)


PROBE_STATES = ("ok", "limited", "misconfigured", "suspect",
                "degraded", "down", "unknown")


def safe_probe_detail(detail):
    """Legacy classifications only; provider/CLI bodies never enter status/DB."""
    fields = {"l1": PROBE_STATES, "l2": {"pass", "fail", "not-run"},
              "source": {"keyround", "probe", "probe_route"}}
    return {key: value for key, value in detail.items()
            if key in fields and isinstance(value, str) and value in fields[key]}


def ingest_probe(state, doc):
    """Store one probe_route result (POST /api/v1/probe body).
    Returns (ok, error): validates shape, records probe_detail + probe
    state, busts the matrix cache. Never raises on bad input."""
    if not isinstance(doc, dict):
        return False, "body must be an object"
    missing = [k for k in ("provider", "model", "state")
               if not doc.get(k)]
    if missing:
        return False, "missing: " + ",".join(missing)
    if not isinstance(doc["state"], str) or doc["state"] not in PROBE_STATES:
        return False, "bad state"
    routes = [r for r in state["routes"]
              if r.get("provider") == doc["provider"]
              and r.get("model") == doc["model"]]
    if not routes:
        return False, "unknown route"
    if not isinstance(doc.get("detail"), dict):
        return False, "detail must be an object"
    claim = doc.get("connection_id") or ""
    if claim:
        targets = [r for r in routes if connection_id(r) == claim]
        if not targets:
            return False, "unknown connection"
    else:
        if len(routes) != 1:
            return False, "connection_id required for ambiguous route"
        targets = routes
    record = {"provider": doc["provider"], "model": doc["model"],
              "state": doc["state"], "detail": safe_probe_detail(doc["detail"]),
              "checked_at": doc.get("checked_at", "") if probe_epoch(doc.get("checked_at")) is not None else ""}
    # Every targeted route keeps its own verdict: same-model keys are each
    # probed separately, so each connection id records its own result.
    import copy as _copy
    template = record
    for route in targets:
        each = connection_id(route)
        record = _copy.deepcopy(template)
        # Consecutive-failure streak travels inside the record (auditor
        # 17:34): previous streak +1 on down, reset on ok — persisted by
        # probe_db_save, so backoff accumulates across ingests and
        # survives task restarts (fresh allocs fall back to the baked
        # ledger baseline via overlay_keyqueue_live).
        if (record.get("detail") or {}).get("source") == "keyround":
            prev = (state["probe_detail"].get(each) or {}).get(
                "detail") or {}
            try:
                prev_streak = int(prev.get("dead_streak", 0))
            except (ValueError, TypeError):
                prev_streak = 0
            record["detail"]["dead_streak"] = (
                prev_streak + 1 if record.get("state") == "down"
                else 0)
        state["probe_detail"][each] = record
        state["probe"][each] = doc["state"]
        probe_db_save(each, record)
    state["matrix_cache"] = None
    return True, ""


def accepted(auth, token):
    """Bearer check against one token or a tuple (current + next).
    Rotation: pass (KEEPER_TOKEN, KEEPER_TOKEN_NEXT); empty entries never
    match, so an unset NEXT changes nothing."""
    toks = token if isinstance(token, (tuple, list)) else (token,)
    return any(t and secrets.compare_digest(auth.encode(), ("Bearer " + t).encode()) for t in toks)


# --- HTTP observability (request IDs, structured access log, counters) ---
# Every request gets one JSON line on stderr (Alloy ships raw lines to Loki;
# query with `| json`). No secret VALUES ever: only a sha12 credential
# fingerprint, the principal class, and the machine-readable error code.
# Contract-safe: route() is untouched; X-Request-ID is an additive response
# header; /metrics gains additive series only.

REQ_ID_HEADER = "X-Request-ID"
MAX_LOG_FIELD = 200


def http_req_id(headers):
    """Honor a sane incoming X-Request-ID, else mint one."""
    raw = ""
    for key, value in headers.items():
        if key.lower() == "x-request-id":
            raw = (value or "")[:64]
    clean = "".join(c for c in raw if c.isalnum() or c in "-_.")
    return clean[:64] if len(clean) >= 4 else secrets.token_hex(8)


def http_trace_id(headers):
    """W3C traceparent -> 32-hex trace-id for Loki/Tempo correlation ("" if absent)."""
    raw = ""
    for key, value in headers.items():
        if key.lower() == "traceparent":
            raw = value or ""
    parts = raw.strip().split("-")
    if (len(parts) == 4 and len(parts[1]) == 32
            and all(c in "0123456789abcdefABCDEF" for c in parts[1])):
        return parts[1].lower()
    return ""


def norm_http_route(clean_path):
    """Low-cardinality route class for metrics (never raw IDs)."""
    if clean_path in ("/healthz", "/login", "/metrics"):
        return clean_path[1:]
    if clean_path in ("/v1/models", "/v1/chat/completions"):
        return "inference"
    if clean_path in ("/packs", "/report", "/guides", "/signin", "/"):
        return "pages"
    if clean_path in ("/api/v1/session", "/api/v1/session/logout"):
        return "session"
    if clean_path.startswith("/api/v2/"):
        return "api_v2"
    if clean_path.startswith("/api/v1/"):
        return "api_v1"
    if clean_path.startswith("/v1/route/") or clean_path.startswith("/v1/guide/"):
        return "route_info"
    return "other"


def http_error_code(status, body):
    """Machine-readable code from keeper JSON error envelopes, else ""."""
    if status < 400 or not isinstance(body, (bytes, bytearray)):
        return ""
    try:
        err = json.loads(bytes(body).decode("utf8", "replace")).get("error") or {}
    except ValueError:
        return ""
    code = err.get("code", "")
    return str(code)[:64] if isinstance(code, str) and code else ""


def fp_cred(auth):
    """sha12 fingerprint of a credential header (never the value)."""
    if not auth:
        return ""
    return hashlib.sha256(auth.encode()).hexdigest()[:12]


def service_consumer(state, auth):
    """Consumer name for a service bearer, else "".

    Per-consumer tokens (KEEPER_SERVICE_TOKENS) attribute usage to a caller
    that cannot spoof another's name; the shared legacy token is 'legacy'.
    Every configured token is compared (constant time per token)."""
    if not state or not auth:
        return ""
    found = ""
    tokens = dict(state.get("service_tokens") or {})
    if state.get("service_token"):
        tokens.setdefault("legacy", state["service_token"])
    for name, value in sorted(tokens.items()):
        if value and secrets.compare_digest(auth, "Bearer " + value):
            found = found or name
    return found


def classify_caller(headers, token, service_token, state):
    """(principal, cred_fp): none | service | admin | session. Fingerprint only."""
    auth = ""
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value
    if (service_token and secrets.compare_digest(auth, "Bearer " + service_token)) or service_consumer(state, auth):
        return "service", fp_cred(auth)
    if accepted(auth, token):
        return "admin", fp_cred(auth)
    try:
        if state is not None and _valid_session(state, _session_raw(headers)):
            return "session", fp_cred("cookie")
    except Exception:
        pass
    return "none", (fp_cred(auth) if auth else "")


def http_observe(state, route_cls, code, ms):
    """Prometheus counters for HTTP responses (thread-safe; never raises)."""
    if state is None:
        return
    try:
        lock = state.setdefault("_http_lock", threading.Lock())
        with lock:
            table = state.setdefault("_http", {})
            key = "%s|%d" % (route_cls, code)
            row = table.get(key) or [0, 0]
            row[0] += 1
            row[1] += int(ms)
            table[key] = row
    except Exception:
        pass


def http_access_record(ts, req_id, trace_id, method, path, status, ms,
                       principal, cred_fp, err, ua, consumer="", served=None):
    """Whitelisted-field access record — secret values cannot be represented."""
    rec = {"ts": ts, "req": req_id, "trace": trace_id, "method": method,
           "path": path[:MAX_LOG_FIELD], "status": status, "ms": int(ms),
           "principal": principal, "cred": cred_fp, "err": err,
           "ua": (ua or "")[:80]}
    if consumer:
        rec["consumer"] = consumer[:64]
    for key, value in (served or {}).items():
        rec[key] = str(value)[:MAX_LOG_FIELD]
    return rec


SERVED_HEADERS = {"x-keeper-model": "model", "x-keeper-provider": "provider",
                  "x-keeper-tier": "tier"}
INTERNAL_TRACE_HEADER = "X-Keeper-Internal-Trace"


def served_fields(resp_headers):
    """What served an inference request, from Keeper's own response headers."""
    out = {}
    for key, value in resp_headers or ():
        if key.lower() in SERVED_HEADERS:
            out[SERVED_HEADERS[key.lower()]] = value
    return out


def http_parent_span(headers):
    """W3C traceparent parent span-id (16 hex) or ""."""
    for key, value in headers.items():
        if key.lower() == "traceparent":
            parts = (value or "").strip().split("-")
            if (len(parts) == 4 and len(parts[2]) == 16
                    and all(c in "0123456789abcdefABCDEF" for c in parts[2])):
                return parts[2].lower()
    return ""


def request_ctx(headers, consumer):
    """Attribution context for inference: caller, request id, trace id."""
    trace = http_trace_id(headers)
    for key, value in headers.items():
        if key == INTERNAL_TRACE_HEADER and not trace:
            trace = value
    return {"consumer": consumer, "req_id": http_req_id(headers), "trace_id": trace}


def route(method, path, headers, token, body=None, query="", state=None):
    """Pure routing: (status, body_bytes, extra_headers). No sockets.

    L1 contract preserved: with state=None only /healthz + auth + 404.
    """
    parsed = urllib.parse.urlparse(path)
    clean_path = parsed.path or "/"
    query = parsed.query or query
    # Edge tolerance (2026-09-21, field-proven via access logs): the public
    # edge concatenates its /v1 service-URL base with the full request path,
    # so /v1/models arrives as /v1/v1/models (principal=service log lines).
    # Collapse the doubled prefix — no legit route starts with /v1/v1 — so
    # public clients work regardless of edge config. Loopback clients send
    # correct paths and never hit this branch.
    if clean_path == "/v1/v1":
        clean_path = "/"
    elif clean_path.startswith("/v1/v1/"):
        clean_path = clean_path[3:]
    if method == "GET" and clean_path == "/healthz":
        return 200, b"ok", [("Content-Type", "text/plain")]
    if method == "GET" and clean_path == "/login":
        return text_resp(200, page_login(), "text/html")
    auth = ""
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value
    consumer = service_consumer(state, auth)
    if consumer:
        if method == "GET" and clean_path == "/v1/models":
            return service_api.models()
        if method == "POST" and clean_path == "/v1/chat/completions":
            return service_api.chat(state, body, ctx=request_ctx(headers, consumer))
        # Scope refusal: principal IS the service token but the path is not
        # an inference endpoint. Debuggable via this request's stderr
        # access-log line (principal=service, err=inference_only_token).
        return service_api.error(403, "inference_only_token")
    # Sessions may read private non-value views. Only the enumerated v2
    # mutations accept cookies, and require same-origin + session-bound CSRF.
    cookie_ok = (state is not None
                 and _valid_session(state, _session_raw(headers)))
    bearer_ok = accepted(auth, token)
    if cookie_ok and not bearer_ok and method == "POST" and clean_path in api_v2.MUTATIONS:
        if not api_v2.browser_mutation_ok(state, headers, _session_raw(headers)):
            return api_v2.response(403, {"error": "csrf_required"})
    secret_get = clean_path == "/packs" or clean_path.startswith("/v1/route/")
    via_cookie = cookie_ok and not secret_get and (
        method == "GET" or (method == "POST" and clean_path in api_v2.MUTATIONS) or (method == "POST"
                              and clean_path == "/api/v1/session/logout"))
    if not accepted(auth, token) and not via_cookie:
        return 401, b"unauthorized", [("Content-Type", "text/plain")]
    if state is None:
        return 404, b"not found", [("Content-Type", "text/plain")]
    if method == "POST" and clean_path == "/api/v1/session":
        # Minting requires the bearer itself (never a session cookie).
        if not accepted(auth, token):
            return 401, b"unauthorized", [("Content-Type", "text/plain")]
        raw = secrets.token_urlsafe(32)
        with _SESSION_LOCK:
            state.setdefault("sessions", {})[
                hashlib.sha256(raw.encode()).hexdigest()] = time.time() + SESSION_TTL
        return json_resp(200, {"ok": True}, [_set_session_cookie(raw)])
    if method == "POST" and clean_path == "/api/v1/session/logout":
        raw = _session_raw(headers)
        if raw:
            with _SESSION_LOCK:
                state.get("sessions", {}).pop(
                    hashlib.sha256(raw.encode()).hexdigest(), None)
        return json_resp(200, {"ok": True}, [_clear_session_cookie()])
    if clean_path.startswith("/api/v2/"):
        return api_v2.handle(state, method, clean_path, body, _session_raw(headers) if cookie_ok else "")
    if "availability" in state and clean_path in dashboard.ASSETS and method == "GET":
        return dashboard.serve(clean_path)
    params = urllib.parse.parse_qs(query)

    if method == "GET" and clean_path == "/packs":
        refresh = params.get("refresh", ["0"])[0] == "1"
        doc = freeze(state, enumerate_inventory(state["routes"],
                                                refresh))
        tag = '"%s"' % etag_for(doc)
        if headers.get("If-None-Match", headers.get("if-none-match", "")) == tag:
            return 304, b"", [("ETag", tag)]
        return 200, json.dumps(doc).encode(), [
            ("Content-Type", "application/json"),
            ("ETag", tag), ("Cache-Control", "no-store, private")]

    if method == "POST" and clean_path == "/feedback":
        try:
            doc = json.loads((body or b"").decode("utf-8") or "{}")
        except Exception:
            doc = None
        missing, bad = validate_feedback(doc)
        if missing:
            return json_resp(422, {"missing": missing})
        if bad is not None:
            return json_resp(422, {"error": "invalid_error_class"})
        spool_feedback(state, doc)
        return json_resp(202, {"ok": True})

    if method == "POST" and clean_path == "/api/v1/probe":
        try:
            probe_doc = json.loads((body or b"").decode("utf-8") or "{}")
        except Exception:
            return 422, b"bad json", [("Content-Type", "text/plain")]
        ok, err = ingest_probe(state, probe_doc)
        if not ok:
            return 422, ("probe rejected: " + err).encode(), [
                ("Content-Type", "text/plain")]
        return json_resp(202, {"ok": True,
                              "keeperPackVersion": KEEPER_PACK_VERSION})

    if method == "GET" and clean_path == "/v1/providers":
        return json_resp(200, {"providers": provider_view(state),
                               "keeperPackVersion": KEEPER_PACK_VERSION})

    if method == "GET" and clean_path.startswith("/v1/guide/"):
        view = guide_view(state, clean_path[len("/v1/guide/"):])
        if view is None:
            return 404, b"not found", [("Content-Type", "text/plain")]
        return json_resp(200, view)

    if method == "POST" and clean_path == "/v1/chat/completions":
        try:
            req = json.loads((body or b"").decode("utf-8") or "{}")
        except Exception:
            req = None
        if not isinstance(req, dict):
            return json_resp(400, {"error": {"message": "bad JSON",
                                             "type": "invalid_request",
                                             "code": "invalid_request"}})
        if "availability" in state or req.get("model") == service_api.ALIAS:
            return service_api.chat(state, body, allow_exact=True,
                                    ctx=request_ctx(headers, "admin"))
        code, doc, sse = chat_completions(state, req, dict(headers))
        if sse is not None:
            return code, sse, [("Content-Type", "text/event-stream")]
        return json_resp(code, doc)

    if method == "GET" and clean_path == "/v1/models":
        return json_resp(200, models_view(state))

    if method == "GET" and clean_path.startswith("/v1/route/"):
        view = route_view(state, clean_path[len("/v1/route/"):])
        if view is None:
            return 404, b"not found", [("Content-Type", "text/plain")]
        return json_resp(200, view, api_v2.NO_STORE)

    if method == "GET" and clean_path == "/api/v1/matrix":
        refresh = params.get("refresh", ["0"])[0] == "1"
        return json_resp(200, matrix_view(state, refresh))

    if method == "GET" and clean_path == "/api/v1/accounts":
        return json_resp(200, accounts_view(state))

    if method == "GET" and clean_path == "/api/v1/health":
        return json_resp(200, health_view(state))

    if method == "GET" and clean_path == "/api/v1/key-queue":
        # Pool heartbeat ledger (key names + verdicts, never values).
        return json_resp(200, keyqueue_view(state))

    if method == "GET" and clean_path == "/api/v1/detail":
        # Stored probe evidence for one connection (bearer-gated like
        # everything else). Records carry provider/model/state/detail
        # (incl. L2 CLI text) + checked_at — never credentials.
        cid = params.get("connection", [""])[0]
        det = (state.get("probe_detail") or {}).get(cid)
        if det is None:
            return json_resp(404, {"ok": False,
                                   "error": "no probe record"})
        if "availability" in state:
            det = {"provider": det.get("provider"), "model": det.get("model"),
                   "state": "legacy_unverified", "detail": safe_probe_detail(det.get("detail") or {}),
                   "checked_at": det.get("checked_at") if probe_epoch(det.get("checked_at")) is not None else ""}
        return json_resp(200, {"ok": True, "record": det})

    if method == "GET" and clean_path == "/metrics":
        return text_resp(200, metrics_view(state),
                         "text/plain; version=0.0.4")

    if method == "GET" and clean_path == "/":
        refresh = params.get("refresh", ["0"])[0] == "1"
        if refresh:
            state["matrix_cache"] = None
        return text_resp(200, page_index(state), "text/html")

    if method == "GET" and clean_path == "/guides":
        return text_resp(200, page_guides(state), "text/html")

    if method == "GET" and clean_path == "/signin":
        return text_resp(200, page_signin(state), "text/html")

    if method == "GET" and clean_path == "/report":
        return text_resp(200, page_report(state), "text/html")

    return 404, b"not found", [("Content-Type", "text/plain")]


class KeeperHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        sys.stderr.write("keeper request failed\n")


class H(BaseHTTPRequestHandler):
    server_version = "keeper/2"
    token = ""
    token_next = ""  # rotation window: also accepted while set
    state = None

    def log_message(self, *a):
        pass  # replaced by structured per-request JSON (see _serve)

    def _serve(self, method):
        t0 = time.time()
        headers = {k: v for k, v in dict(self.headers).items()
                   if k.lower() not in ("x-request-id", INTERNAL_TRACE_HEADER.lower())}
        req_id = http_req_id(dict(self.headers))
        headers["X-Request-Id"] = req_id  # route() re-derives the same id
        parent_span = http_parent_span(headers)
        trace_id = http_trace_id(headers)
        if not trace_id:
            import tracing as _tracing
            trace_id = _tracing.fresh_trace_id()  # always logged: Loki<->Tempo join
            headers[INTERNAL_TRACE_HEADER] = trace_id
        if method == "GET":
            code, body, resp_headers = route(
                "GET", self.path, headers,
                (self.token, self.token_next), state=self.state)
        else:
            code, body, resp_headers = route(
                "POST", self.path, headers,
                (self.token, self.token_next),
                body=self._read_body(), state=self.state)
        self._send(code, body, list(resp_headers) + [(REQ_ID_HEADER, req_id)])
        ms = (time.time() - t0) * 1000
        clean = urllib.parse.urlparse(self.path).path or "/"
        http_observe(self.state, norm_http_route(clean), code, ms)
        principal, cred_fp = classify_caller(
            headers, (self.token, self.token_next),
            (self.state or {}).get("service_token", ""), self.state)
        auth = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        consumer = service_consumer(self.state, auth) or (
            "admin" if principal == "admin" else "")
        served = served_fields(resp_headers)
        ua = ""
        for key, value in headers.items():
            if key.lower() == "user-agent":
                ua = value
        rec = http_access_record(
            datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            req_id, trace_id, method, clean, code, ms, principal, cred_fp,
            http_error_code(code, body), ua, consumer, served)
        sys.stderr.write(json.dumps(rec, sort_keys=True) + "\n")
        try:
            import tracing as _tracing
            attrs = {"keeper.request_id": req_id}
            if consumer:
                attrs["keeper.consumer"] = consumer
            for key, value in served.items():
                attrs["keeper." + key] = value
            _tracing.emit_request_span(
                trace_id, norm_http_route(clean), code, ms, principal,
                http_error_code(code, body), attrs=attrs, parent_span_id=parent_span)
        except Exception:
            pass

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        names = {key.lower() for key, value in headers}
        for key, value in [("Cache-Control", "no-store, private"), ("Referrer-Policy", "no-referrer"),
                           ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY")]:
            if key.lower() not in names:
                self.send_header(key, value)
        streaming = not isinstance(body, bytes)
        if not streaming:
            self.send_header("Content-Length", str(len(body)))
        else:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if streaming:
            try:
                for chunk in body:
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                body.close()
        elif body:
            self.wfile.write(body)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""


def probe_db_path():
    # Empty (tests, dev) = persistence disabled; production sets
    # PROBE_DB=${NOMAD_ALLOC_DIR}/probe.db (survives task restarts,
    # dies with the alloc — deploys fall back to probe-seed.json).
    return os.environ.get("PROBE_DB", "")


def probe_db_save(cid, record):
    """Upsert one probe_detail record; never raises (probe path must
    not break on a sick disk)."""
    if not probe_db_path():
        return
    try:
        import sqlite3
        con = sqlite3.connect(probe_db_path())
        try:
            con.execute("CREATE TABLE IF NOT EXISTS probe_detail "
                        "(cid TEXT PRIMARY KEY, record TEXT NOT NULL)")
            con.execute("INSERT OR REPLACE INTO probe_detail VALUES "
                        "(?, ?)", (cid, json.dumps(record)))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def probe_db_load():
    """All stored records; {} when the db is missing/empty/broken."""
    try:
        import sqlite3
        if not os.path.exists(probe_db_path()):
            return {}
        con = sqlite3.connect(probe_db_path())
        try:
            rows = con.execute(
                "SELECT cid, record FROM probe_detail").fetchall()
        finally:
            con.close()
        out = {}
        for cid, raw in rows:
            try:
                doc = json.loads(raw)
            except ValueError:
                continue
            if isinstance(doc, dict):
                out[cid] = doc
        return out
    except Exception:
        return {}


def load_probe_seed():
    """Boot baseline from baked probe-seed.json (heartbeat verdicts).
    {} when missing — keeper just starts unknown like before."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "probe-seed.json"),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict):
            return {k: v for k, v in doc.items()
                    if isinstance(v, dict)}
    except (OSError, ValueError):
        pass
    return {}


def hydrate_probe_state(state):
    """Boot: seed baseline first, sqlite overlay (fresher, same-alloc
    restarts) wins. Mirrors ingest_probe's twin maps."""
    merged = dict(load_probe_seed())
    merged.update(probe_db_load())
    for cid, record in merged.items():
        state["probe_detail"][cid] = record
        if isinstance(record.get("state"), str):
            state["probe"][cid] = record["state"]
    if merged:
        state["matrix_cache"] = None
    return len(merged)


def main():
    token = require_token(os.environ.get("KEEPER_TOKEN", ""))
    H.token = token
    H.token_next = os.environ.get("KEEPER_TOKEN_NEXT", "")
    os.umask(0o077)
    H.state = make_state(token, load_seed(os.environ.get("SEED_FILE", "")))
    from runtime import initialize, start_worker
    initialize(H.state, os.environ.get("AVAILABILITY_DB", ""),
               os.environ.get("PUBLIC_ORIGIN", ""), os.environ.get("KEEPER_SERVICE_TOKEN", ""),
               (H.token_next,), os.environ.get("KEEPER_ZENCLI_TOKEN", ""),
               service_tokens=json.loads(os.environ.get("KEEPER_SERVICE_TOKENS") or "{}"))
    start_worker(H.state)
    n = hydrate_probe_state(H.state)
    print("keeper v2 port=%d probe_hydrated=%d" % (PORT, n),
          flush=True)
    KeeperHTTPServer((os.environ.get("BIND", "127.0.0.1"), PORT), H).serve_forever()


if __name__ == "__main__":
    main()
