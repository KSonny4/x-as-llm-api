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
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import aa
import inventory as inventory_mod
import matrix as matrix_mod
import translate as translate_mod

PORT = int(os.environ.get("PORT", "8080"))
KEEPER_PACK_VERSION = "v2"

SESSION_COOKIE = "keeper_session"
SESSION_TTL = 12 * 3600  # 12h browser sessions, in-memory: restart = re-login

# Assignable in tests to stub upstream providers (no live calls in suite).
urlopen = urllib.request.urlopen

# Hook for model inventory; tests stub server.enumerate_inventory.
enumerate_inventory = inventory_mod.get_inventory

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
        "probe_detail": {},  # connection_id -> probe_route result (L1/L2)
        "matrix_cache": None,
        "sessions": {},  # sha256(raw cookie) -> expiry epoch (GET-only login)
    }


def connection_id(route):
    return str(route.get("connection_id") or
               (route.get("provider", "") + "/" + route.get("model", "")))


def find_route(state, model):
    for route in state["routes"]:
        if route.get("model") == model:
            return route
    return None


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
    sessions = state.setdefault("sessions", {})
    for key in [k for k, exp in sessions.items() if exp <= now]:
        del sessions[key]
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
    """Prometheus text: divergent gauge + per-connection probe timestamp.
    Only connections with a recorded dual verdict get series (L2 runs on
    demand, so 'no series' means 'never dual-probed', not 'fine')."""
    lines = [
        "# HELP keeper_route_divergent L1 curl fails while L2 opencode CLI passes.",
        "# TYPE keeper_route_divergent gauge",
        "# HELP keeper_probe_checked_at_seconds Unix time of last dual probe.",
        "# TYPE keeper_probe_checked_at_seconds gauge",
    ]
    for cid in sorted((state.get("probe_detail") or {})):
        det = state["probe_detail"][cid] or {}
        verdict = matrix_mod.dual_verdict(det)
        labels = 'provider="%s",model="%s",connection="%s"' % (
            prom_esc(det.get("provider", "")),
            prom_esc(det.get("model", "")), prom_esc(cid))
        lines.append("keeper_route_divergent{%s} %d"
                     % (labels, 1 if verdict["divergent"] else 0))
        ts = probe_epoch(det.get("checked_at", ""))
        if ts is not None:
            lines.append("keeper_probe_checked_at_seconds{%s} %d"
                         % (labels, ts))
    return "\n".join(lines) + "\n"


def health_view(state):
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


def _worst_state(states):
    """Worst of a set of cell states for provider summaries."""
    states = [str(s) for s in states]
    if not states:
        return "unknown"
    return min(states, key=lambda s: _STATE_RANK.get(s, 2))


def page_index(state):
    """Server-rendered matrix + just-in-time poller.

    The initial table is rendered here (works without JS); the embedded
    script re-reads the SAME agent endpoint browsers would use anyway
    (GET /api/v1/matrix?refresh=1) every 30s and re-renders cells in
    place. A failed fetch surfaces a stale banner — never silent old data.
    DOM is built with textContent (no innerHTML) so route names cannot
    inject markup."""
    doc = matrix_view(state)
    col_ids = [p["id"] for p in doc["providers"]]
    probed = {c: _col_probed(doc, c) for c in col_ids}
    groups = []
    for p in doc["providers"]:
        if p.get("provider") not in groups:
            groups.append(p.get("provider"))
    cols_of = {g: [p for p in doc["providers"]
                    if p.get("provider") == g] for g in groups}

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
            mod_head.append(
                '<th class="mod" data-p="%s" hidden>%s</th>'
                % (html.escape(g or ""), html.escape(label)))
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
                if entries:
                    cells.append(
                        '<td class="mod" data-p="%s" hidden>%s</td>'
                        % (html.escape(g or ""), ", ".join(
                            _cell_html(e) for e in entries)))
                elif probed[p["id"]]:
                    cells.append(
                        '<td class="mod" data-p="%s" hidden>\u2014</td>'
                        % html.escape(g or ""))
                else:
                    cells.append(
                        '<td class="mod unprobed" data-p="%s" hidden '
                        'title="unprobed">\u2014</td>'
                        % html.escape(g or ""))
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
            "<p id=\"stale\"></p>"
            "<table id=\"tbl\" data-cols=\"%s\"><thead>"
            "<tr><th>owner</th>%s</tr><tr><th></th>%s</tr></thead>"
            "<tbody id=\"cells\">%s</tbody></table>"
            "<p><small id=\"updated\"></small> "
            "<button id=\"lo\">log out</button></p>"
            "<p class=\"legend\">green ok · amber suspect · red down · "
            "gray unknown · <span class=\"div\">DIVERGENT</span> split · "
            "gray — unprobed</p>"
            "<h2>diagnostics.unassigned</h2><ul id=\"unassigned\">%s</ul>"
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
            "const p=th.dataset.p;"
            "document.querySelectorAll('#tbl .mod').forEach(el=>{"
            "if(el.dataset.p===p)el.hidden=!el.hidden;});"
            "if(EXP.has(p))EXP.delete(p);else EXP.add(p);});"
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
            "const init=document.getElementById('tbl').dataset.cols.split(',');"
            "const ids=d.providers.map(p=>p.id);"
            "if(ids.join(',')!==init.join(',')){S.style.display='block';"
            "S.textContent='new models available — reload the page.';return;}"
            "T.replaceChildren(...d.rows.map(row=>{"
            "const tr=document.createElement('tr'),"
            "td=document.createElement('td');"
            "td.textContent=row.email;tr.appendChild(td);"
            "for(const g of groups){"
            "const cols=d.providers.filter(p=>p.provider===g),st=[];"
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
            "c.dataset.p=g;c.hidden=!EXP.has(g);"
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
            "U.textContent='updated '+new Date().toLocaleTimeString();"
            "}catch(e){S.style.display='block';"
            "S.textContent='stale — refresh failed ('+e.message+')';}}"
            "setInterval(poll,30000);"
            "</script></body></html>"
            % (",".join(html.escape(c) for c in col_ids),
               "".join(prov_head), "".join(mod_head),
               "".join(rows), unassigned or "<li>none</li>"))


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
    if doc["state"] not in PROBE_STATES:
        return False, "bad state: %s" % doc["state"]
    routes = [r for r in state["routes"]
              if r.get("provider") == doc["provider"]
              and r.get("model") == doc["model"]]
    if not routes:
        return False, "unknown route: %s/%s" % (doc["provider"],
                                                 doc["model"])
    cid = connection_id(routes[0])
    if not isinstance(doc.get("detail"), dict):
        return False, "detail must be an object"
    record = {"provider": doc["provider"], "model": doc["model"],
              "state": doc["state"], "detail": doc["detail"],
              "checked_at": doc.get("checked_at", "")}
    state["probe_detail"][cid] = record
    state["probe"][cid] = doc["state"]
    state["matrix_cache"] = None
    return True, ""


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
    if method == "GET" and clean_path == "/login":
        return text_resp(200, page_login(), "text/html")
    auth = ""
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value
    # Cookie sessions are GET-only, except logout (destroying your own
    # session is safe; SameSite=Lax already blocks cross-site POST). Browsers
    # read pages, never mutate state.
    cookie_ok = (state is not None
                 and _valid_session(state, _session_raw(headers)))
    via_cookie = cookie_ok and (
        method == "GET" or (method == "POST"
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
        state.setdefault("sessions", {})[
            hashlib.sha256(raw.encode()).hexdigest()] = time.time() + SESSION_TTL
        return json_resp(200, {"ok": True}, [_set_session_cookie(raw)])
    if method == "POST" and clean_path == "/api/v1/session/logout":
        raw = _session_raw(headers)
        if raw:
            state.get("sessions", {}).pop(
                hashlib.sha256(raw.encode()).hexdigest(), None)
        return json_resp(200, {"ok": True}, [_clear_session_cookie()])
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
