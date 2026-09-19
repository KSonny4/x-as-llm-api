#!/usr/bin/env python3
"""L4 probe worker (Wave 1 lane): L1 curl probe + L2 opencode-CLI probe.

Pure + stub-testable. States: ok | limited | misconfigured | suspect |
degraded | down. Design §5: 429 => limited+backoff (never deny);
auth-shaped denial => suspect + feedback; wrong wire => misconfigured.
"""
import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BACKOFF_MIN = 5
ANTHROPIC_VERSION = "2023-06-01"
# Fleet identity: Zen's edge (and who knows who next) blocks the
# Python-urllib default UA with 403. Honest, documented, tested.
FLEET_UA = "keeper-probe/1.0"


def _now():
    return datetime.now(timezone.utc)


def _get(route, path):
    req = urllib.request.Request(
        route["base_url"].rstrip("/") + path,
        headers={"Authorization": "Bearer " + route.get("api_key", ""),
                 "User-Agent": FLEET_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:  # refused, timeout, DNS — L1 miss, not deny
        return None, f"connect-fail: {e}"


def _post(route, path, payload, extra_headers=None):
    raw = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + route.get("api_key", ""),
               "User-Agent": FLEET_UA}
    headers.update(extra_headers or {})
    req = urllib.request.Request(route["base_url"].rstrip("/") + path,
                                 data=raw, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return None, f"connect-fail: {e}"


def _feedback(route, http_status, error_class):
    return {"ts": _now().isoformat(), "provider": route.get("provider", ""),
            "model": route.get("model", ""), "status": http_status,
            "errorClass": error_class, "httpStatus": http_status}


def _non_empty_text(s):
    return isinstance(s, str) and bool(s.strip())


def _probe_l1_gemini(route):
    """Gemini has no OpenAI /models leg: ping generateContent directly."""
    code, body = _post(
        route, "/v1beta/models/%s:generateContent" % route.get("model", ""),
        {"contents": [{"parts": [{"text": "ping"}]}]},
        {"x-goog-api-key": route.get("api_key", "")})
    if code == 200:
        try:
            text = json.loads(body)["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            text = ""
        if _non_empty_text(text):
            return "ok", {}, None
        return "suspect", {"reason": "empty text"}, _feedback(route, 200, "unknown")
    if code in (404, 415, 422):
        return "misconfigured", {"reason": body[:200]}, None
    if code is None:
        return "suspect", {"reason": body}, None
    if code == 429:
        return "limited", {"backoff_at": (_now() + timedelta(minutes=BACKOFF_MIN)).isoformat()}, None
    if code in (401, 403):
        return "suspect", {"reason": body[:200]}, _feedback(route, code, "auth")
    return "suspect", {"reason": body[:200]}, _feedback(route, code or 0, "unknown")


def probe_l1(route):
    """Returns (outcome, detail, feedback|None)."""
    wire = route.get("wire", "openai")
    if wire == "gemini":
        return _probe_l1_gemini(route)
    code, body = _get(route, "/models")
    if code is None:
        return "suspect", {"reason": body}, None
    # GET-leg failures stay suspect: a missing /models (or 404/5xx here)
    # cannot distinguish wrong-wire from down. Only the chat-leg 404/415/422
    # below is classified misconfigured (route wrong, provider alive).
    if code == 429:
        return "limited", {"backoff_at": (_now() + timedelta(minutes=BACKOFF_MIN)).isoformat()}, None
    if code in (401, 403):
        return "suspect", {"reason": body[:200]}, _feedback(route, code, "auth")
    if code != 200:
        cls = "upstream_5xx" if code >= 500 else "unknown"
        return "suspect", {"reason": body[:200]}, _feedback(route, code, cls)
    try:
        models = json.loads(body).get("data", [])
    except Exception:
        models = []
    if not models:
        return "suspect", {"reason": "empty models"}, _feedback(route, 200, "unknown")

    wire = route.get("wire", "openai")
    if wire == "anthropic":
        code, body = _post(route, "/v1/messages",
                           {"model": route["model"], "max_tokens": 8,
                            "messages": [{"role": "user", "content": "ping"}]},
                           {"x-api-key": route.get("api_key", ""),
                            "anthropic-version": ANTHROPIC_VERSION})
        if code == 200:
            try:
                text = json.loads(body)["content"][0]["text"]
            except Exception:
                text = ""
            if _non_empty_text(text):
                return "ok", {}, None
            return "suspect", {"reason": "empty text"}, _feedback(route, 200, "unknown")
    else:
        code, body = _post(route, "/chat/completions",
                           {"model": route["model"], "max_tokens": 8,
                            "messages": [{"role": "user", "content": "ping"}]})
        if code == 200:
            try:
                text = json.loads(body)["choices"][0]["message"]["content"]
            except Exception:
                text = ""
            if _non_empty_text(text):
                return "ok", {}, None
            return "suspect", {"reason": "empty text"}, _feedback(route, 200, "unknown")
    if code in (404, 415, 422):
        return "misconfigured", {"reason": body[:200]}, None
    if code is None:
        return "suspect", {"reason": body}, None
    if code == 429:
        return "limited", {"backoff_at": (_now() + timedelta(minutes=BACKOFF_MIN)).isoformat()}, None
    if code in (401, 403):
        return "suspect", {"reason": body[:200]}, _feedback(route, code, "auth")
    return "suspect", {"reason": body[:200]}, _feedback(route, code or 0, "unknown")


def probe_l2(route, env=None):
    """opencode CLI sanity check. Returns (ok, text).
    The CLI model ref is route['l2_ref'] when set (e.g. zen seeds map
    to the CLI's built-in provider id); otherwise provider/model."""
    model = route.get("model", "")
    provider = route.get("provider", "")
    ref = route.get("l2_ref") or (model if "/" in model else f"{provider}/{model}")
    try:
        p = subprocess.run(["opencode", "run", "--pure", "-m", ref, "ping"],
                           capture_output=True, text=True, timeout=120,
                           env=env or os.environ)
    except Exception as e:
        return False, f"exec-fail: {e}"
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    if not out:
        # Empty stdout is the common failure shape (auth/quota errors
        # go to stderr); keep the evidence instead of an empty string.
        out = ("stderr: %s rc=%d" % (err[:400], p.returncode) if err
               else "empty stdout+stderr rc=%d" % p.returncode)
    return (p.returncode == 0 and _non_empty_text(
        (p.stdout or "").strip())), out[:500]


def probe_route(route, report=None, l2env=None):
    """Full decision. Report flips suspect + records fresh L1 evidence."""
    if report is not None:
        out, detail, fb = probe_l1(route)
        res = {"provider": route.get("provider", ""), "model": route.get("model", ""),
                "state": "suspect", "detail": {"report": report, "l1": out, **detail},
                "checked_at": _now().isoformat()}
        # Keep the fresh L1 feedback: the report path re-probes immediately
        # and must not discard what that probe learned.
        if fb is not None:
            res["feedback"] = fb
        return res
    out, detail, fb = probe_l1(route)
    if out in ("ok", "limited", "misconfigured"):
        state = out
        detail = {"l1": out, **detail}
    else:
        ok, text = probe_l2(route, env=l2env)
        state = "degraded" if ok else "down"
        # Record both legs explicitly: the matrix compares L1 vs L2.
        detail = {"l1": out, **detail, "l2": text[:200]}
    res = {"provider": route.get("provider", ""), "model": route.get("model", ""),
           "state": state, "detail": detail, "checked_at": _now().isoformat()}
    if fb is not None:
        res["feedback"] = fb
    return res


def write_status(path, results):
    doc = {"generated_at": _now().isoformat(), "routes": results}
    with open(path, "w") as f:
        json.dump(doc, f, indent=1)
    return path


if __name__ == "__main__":
    import sys
    routes = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    out = [probe_route(r) for r in routes]
    print(json.dumps(write_status("status.json", out)))
