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
    reported, failed = 0, 0
    for route in routes:
        label = "%s/%s" % (route.get("provider", "?"),
                           route.get("model", "?"))
        try:
            res = probe_route(route)
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
    print("dispatch: %d reported, %d failed" % (reported, failed),
          flush=True)
    return 0 if reported else 1


if __name__ == "__main__":
    sys.exit(main())
