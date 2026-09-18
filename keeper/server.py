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
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import aa
import matrix as matrix_mod
import translate as translate_mod

PORT = int(os.environ.get("PORT", "8080"))
KEEPER_PACK_VERSION = "v2"

# Assignable in tests to stub upstream providers (no live calls in suite).
urlopen = urllib.request.urlopen

ANTHROPIC_VERSION = "2023-06-01"
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
        "matrix_cache": None,
    }


def connection_id(route):
    return str(route.get("connection_id") or
               (route.get("provider", "") + "/" + route.get("model", "")))


def find_route(state, model):
    for route in state["routes"]:
        if route.get("model") == model:
            return route
    return None


def freeze(state):
    """Frozen packs snapshot: values for live credentials, signin steps
    otherwise. Values only ever go to bearer-authed callers (see route)."""
    packs = []
    for route in state["routes"]:
        member = {
            "provider": route.get("provider", ""),
            "model": route.get("model", ""),
            "base_url": route.get("base_url", ""),
            "env_var": route.get("env_var", ""),
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
    return {"keeperPackVersion": KEEPER_PACK_VERSION, "packs": packs}


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


def validate_feedback(doc):
    """Returns (missing[], bad_error_class|None)."""
    if not isinstance(doc, dict):
        return list(FEEDBACK_REQUIRED), None
    missing = [f for f in FEEDBACK_REQUIRED if doc.get(f) in (None, "")]
    if missing:
        return missing, None
    if doc.get("errorClass") not in FEEDBACK_ERROR_CLASSES:
        return [], doc.get("errorClass")
    return [], None


def spool_feedback(state, doc):
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


def chat_completions(state, req):
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
        code, body = call_upstream(
            route, "/chat/completions", dict(req, stream=False))
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
    return {"model": model, "baseURL": route.get("base_url", ""),
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
    ensure_aa(state, refresh)
    if state["matrix_cache"] is not None and not refresh:
        return state["matrix_cache"]
    doc = matrix_mod.build_matrix(seed_connections(state), state["probe"],
                                  state["aa_scores"])
    doc["aa_stale"] = state["aa_stale"]
    doc["keeperPackVersion"] = KEEPER_PACK_VERSION
    state["matrix_cache"] = doc
    return doc


def accounts_view(state):
    doc = matrix_view(state)
    return {"emails": doc["emails"],
            "unassigned_count": len(doc["diagnostics"]["unassigned"]),
            "keeperPackVersion": KEEPER_PACK_VERSION}


def health_view(state):
    return {"ok": True, "keeperPackVersion": KEEPER_PACK_VERSION,
            "routes": dict(state["probe"])}


def page_index(state):
    doc = matrix_view(state)
    rows = []
    providers = [p["id"] for p in doc["providers"]]
    for row in doc["rows"]:
        cells = []
        for provider in providers:
            entries = row["cells"].get(provider, [])
            if entries:
                cells.append("<td>%s</td>" % html.escape(
                    ", ".join("%s (%s)" % (e["name"], e["state"])
                              for e in entries)))
            else:
                cells.append("<td>—</td>")
        rows.append("<tr><td>%s</td>%s</tr>" % (html.escape(row["email"]),
                                               "".join(cells)))
    unassigned = "".join("<li>%s</li>" % html.escape(
        "%s (%s)" % (u.get("name", "?"), u.get("provider", "?")))
        for u in doc["diagnostics"]["unassigned"])
    return ("<html><head><title>keeper matrix</title></head><body>"
            "<h1>keeper matrix</h1>"
            "<table><tr><th>owner</th>%s</tr>%s</table>"
            "<h2>diagnostics.unassigned</h2><ul>%s</ul>"
            "</body></html>"
            % ("".join("<th>%s</th>" % html.escape(p) for p in providers),
               "".join(rows), unassigned or "<li>none</li>"))


def page_guides(state):
    cards = []
    for who in GUIDE_WHOS:
        view = guide_view(state, who)
        curls = "\n".join(html.escape(c["curl"]) for c in view["curls"])
        cards.append("<h2>%s</h2><pre>%s\n%s</pre>"
                     % (html.escape(who), html.escape(view["header"]), curls))
    return ("<html><head><title>guides</title></head><body>"
            "<h1>guides</h1>%s</body></html>" % "".join(cards))


def page_signin(state):
    steps = []
    for route in state["routes"]:
        if not route.get("api_key"):
            steps.append("<li>%s: export %s, then re-mint via your "
                         "provider dashboard</li>"
                         % (html.escape(route.get("model", "?")),
                            html.escape(route.get("env_var", "?"))))
    return ("<html><head><title>signin</title></head><body>"
            "<h1>signin: re-mint steps</h1><ul>%s</ul></body></html>"
            % ("".join(steps) or "<li>all routes have live credentials</li>"))


def page_report(state):
    options = "".join("<option>%s</option>" % html.escape(
        "%s/%s:%s" % (r.get("provider", ""), r.get("model", ""),
                      state["probe"].get(connection_id(r), "unknown")))
        for r in state["routes"])
    return ("<html><head><title>report</title></head><body>"
            "<h1>report a route problem</h1>"
            "<p>live route state is shown per option</p>"
            "<form method=\"post\" action=\"/feedback\">"
            "<select name=\"route\">%s</select>"
            "<input name=\"errorClass\" placeholder=\"errorClass\"/>"
            "<input name=\"httpStatus\" placeholder=\"httpStatus\"/>"
            "<button>send</button></form></body></html>" % options)


def accepted(auth, token):
    """Bearer check against one token or a tuple (current + next).
    Rotation: pass (KEEPER_TOKEN, KEEPER_TOKEN_NEXT); empty entries never
    match, so an unset NEXT changes nothing."""
    toks = token if isinstance(token, (tuple, list)) else (token,)
    return any(t and auth == "Bearer " + t for t in toks)


def route(method, path, headers, token, body=None, query="", state=None):
    """Pure routing: (status, body_bytes, extra_headers). No sockets.

    L1 contract preserved: with state=None only /healthz + auth + 404.
    """
    parsed = urllib.parse.urlparse(path)
    clean_path = parsed.path or "/"
    query = parsed.query or query
    if method == "GET" and clean_path == "/healthz":
        return 200, b"ok", [("Content-Type", "text/plain")]
    auth = ""
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value
    if not accepted(auth, token):
        return 401, b"unauthorized", [("Content-Type", "text/plain")]
    if state is None:
        return 404, b"not found", [("Content-Type", "text/plain")]
    params = urllib.parse.parse_qs(query)

    if method == "GET" and clean_path == "/packs":
        doc = freeze(state)
        tag = '"%s"' % etag_for(doc)
        if headers.get("If-None-Match", headers.get("if-none-match", "")) == tag:
            return 304, b"", [("ETag", tag)]
        return 200, json.dumps(doc).encode(), [
            ("Content-Type", "application/json"),
            ("ETag", tag), ("Cache-Control", "max-age=600")]

    if method == "POST" and clean_path == "/feedback":
        try:
            doc = json.loads((body or b"").decode("utf-8") or "{}")
        except Exception:
            doc = None
        missing, bad = validate_feedback(doc)
        if missing:
            return json_resp(422, {"missing": missing})
        if bad is not None:
            return json_resp(422, {"bad_errorClass": bad})
        spool_feedback(state, doc)
        return json_resp(202, {"ok": True})

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
        code, doc, sse = chat_completions(state, req)
        if sse is not None:
            return code, sse, [("Content-Type", "text/event-stream")]
        return json_resp(code, doc)

    if method == "GET" and clean_path == "/v1/models":
        return json_resp(200, models_view(state))

    if method == "GET" and clean_path.startswith("/v1/route/"):
        view = route_view(state, clean_path[len("/v1/route/"):])
        if view is None:
            return 404, b"not found", [("Content-Type", "text/plain")]
        return json_resp(200, view)

    if method == "GET" and clean_path == "/api/v1/matrix":
        refresh = params.get("refresh", ["0"])[0] == "1"
        return json_resp(200, matrix_view(state, refresh))

    if method == "GET" and clean_path == "/api/v1/accounts":
        return json_resp(200, accounts_view(state))

    if method == "GET" and clean_path == "/api/v1/health":
        return json_resp(200, health_view(state))

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


class H(BaseHTTPRequestHandler):
    server_version = "keeper/2"
    token = ""
    token_next = ""  # rotation window: also accepted while set
    state = None

    def log_message(self, *a):
        sys.stderr.write("%s %s %s\n" % (self.log_date_time_string(),
                                         self.command, self.path))

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def do_GET(self):
        code, body, headers = route("GET", self.path, dict(self.headers),
                                    (self.token, self.token_next),
                                    state=self.state)
        self._send(code, body, headers)

    def do_POST(self):
        code, body, headers = route("POST", self.path, dict(self.headers),
                                    (self.token, self.token_next),
                                    body=self._read_body(),
                                    state=self.state)
        self._send(code, body, headers)


def main():
    token = require_token(os.environ.get("KEEPER_TOKEN", ""))
    H.token = token
    H.token_next = os.environ.get("KEEPER_TOKEN_NEXT", "")
    H.state = make_state(token, load_seed(os.environ.get("SEED_FILE", "")))
    print("keeper v2 on 0.0.0.0:%d" % PORT, flush=True)
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
