#!/usr/bin/env python3
"""dispatch.py — on-demand cluster prober (env-driven, stdlib only).

Reads seed routes (SEEDS_JSON or SEED_FILE), runs probe_route per route
(L1 always; L2 opencode CLI only on L1 non-ok — see worker.probe_route),
and POSTs each result to KEEPER_URL/api/v1/probe so the matrix, /metrics
and the Grafana alert see fresh dual verdicts.

Env:
  SEEDS_JSON   {"routes": [...]} inline (preferred: from Nomad -var)
  SEED_FILE    fallback path to seeds JSON
  KEEPER_URL   keeper base (default http://127.0.0.1:8102)
  KEEPER_TOKEN bearer for POST /api/v1/probe (required)

Exit 0 unless nothing could be reported (then 1). Per-route failures
never abort the run; values are never printed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from worker import probe_route  # noqa: E402


def load_routes():
    raw = os.environ.get("SEEDS_JSON", "")
    if raw.strip():
        doc = json.loads(raw)
    else:
        path = os.environ.get("SEED_FILE", "")
        if not path:
            return []
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    routes = doc.get("routes", []) if isinstance(doc, dict) else []
    return [r for r in routes if isinstance(r, dict)]


def is_placeholder(route):
    """Keyless routes are display placeholders (dead markers, unwired
    providers): nothing to probe, so dispatch skips them and their
    matrix cells stay honestly unknown instead of down."""
    return not (route.get("api_key") or "")


def post_result(base, token, result):
    req = urllib.request.Request(
        base.rstrip("/") + "/api/v1/probe",
        data=json.dumps(result).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERR:%s" % e


def trickle_opts(env=None):
    """(sleep_secs, substr) pacing controls from env. Pure/testable."""
    env = env if env is not None else os.environ
    try:
        sleep_s = float(env.get("SLEEP_BETWEEN_SECS", "0") or 0)
    except ValueError:
        sleep_s = 0
    return sleep_s, env.get("ROUTE_SUBSTR", "") or ""


def filter_routes(routes, substr):
    """Keep routes whose connection_id contains substr (all if empty)."""
    if not substr:
        return list(routes)
    return [r for r in routes if substr in (r.get("connection_id") or "")]


def main():
    base = os.environ.get("KEEPER_URL", "http://127.0.0.1:8102")
    token = os.environ.get("KEEPER_TOKEN", "")
    if not token:
        print("dispatch: KEEPER_TOKEN unset — refusing", flush=True)
        return 1
    routes = load_routes()
    if not routes:
        print("dispatch: no routes — nothing to probe", flush=True)
        return 1
    # Trickle controls (env): pace the sweep, optionally subset it.
    # SLEEP_BETWEEN_SECS: pause after each probed route (default 0).
    # ROUTE_SUBSTR: only routes whose connection_id contains it.
    sleep_s, substr = trickle_opts()
    routes = filter_routes(routes, substr)
    if substr:
        print("dispatch: filter %r matches %d routes"
              % (substr, len(routes)), flush=True)
    reported, failed = 0, 0
    for route in routes:
        label = "%s/%s" % (route.get("provider", "?"),
                           route.get("model", "?"))
        if is_placeholder(route):
            print("dispatch: %s skipped (placeholder, no credential)"
                  % label, flush=True)
            continue
        try:
            res = probe_route(route)
            res["connection_id"] = (route.get("connection_id") or
                                     "%s/%s" % (route.get("provider", "?"),
                                                  route.get("model", "?")))
        except Exception as e:
            print("dispatch: %s probe error" % label, flush=True)
            failed += 1
            continue
        code = post_result(base, token, res)
        state = res.get("state", "?")
        div = (res.get("detail") or {}).get("l1", "?"), res.get("state")
        print("dispatch: %s -> %s (l1=%s) posted %s"
              % (label, state, div[0], code), flush=True)
        if code == 202:
            reported += 1
        else:
            failed += 1
        if sleep_s > 0:
            time.sleep(sleep_s)
    print("dispatch: %d reported, %d failed" % (reported, failed),
          flush=True)
    return 0 if reported else 1


if __name__ == "__main__":
    sys.exit(main())
