#!/usr/bin/env python3
"""smoke.py — in-image phase gate, mirrors scripts/smoke.sh (stdlib only).

Runs INSIDE the cluster (nomad alloc exec) so the Nomad-URL smoke needs no
published port and no token ever transits a network: the bearer comes from
the alloc's own environment.

Env:
  BASE               base URL (default http://127.0.0.1:8080)
  KEEPER_TOKEN       primary bearer (required for authed gates)
  KEEPER_TOKEN_NEXT  optional second bearer: asserted 200 (rotation window)
  KEEPER_TOKEN_OLD   optional revoked bearer: asserted 401 (post-revocation)

Exit 0 when every gate prints ok:, else 1. Values are never printed.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:8080").rstrip("/")
FAIL = []


def req(path, token=None, etag=None, method="GET", data=None):
    # NOTE: Cloudflare 403s Python-urllib's default UA on the public
    # hostname (bot rule); identify honestly so smoke works both
    # in-cluster and through the tunnel.
    r = urllib.request.Request(BASE + path, method=method,
                               data=data,
                               headers={"User-Agent": "keeper-smoke/1.0"})
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if etag:
        r.add_header("If-None-Match", etag)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers
    except Exception as e:  # connection refused etc.
        return "ERR:%s" % e, b"", {}


def check(name, want, got):
    if want == got:
        print("ok: %s -> %s" % (name, got), flush=True)
    else:
        print("FAIL: %s (want %s, got %s)" % (name, want, got), flush=True)
        FAIL.append(name)


code, body, _ = req("/healthz")
check("healthz 200 ok", (200, b"ok"), (code, body))
code, _, _ = req("/packs")
check("packs unauth 401", 401, code)

TOKEN = os.environ.get("KEEPER_TOKEN", "")
if not TOKEN:
    print("SKIP: authed gates (KEEPER_TOKEN unset)", flush=True)
else:
    code, _, _ = req("/packs", TOKEN)
    check("packs authed 200", 200, code)
    code, _, headers = req("/packs", TOKEN)
    tag = headers.get("ETag", "")
    if tag:
        code, _, _ = req("/packs", TOKEN, etag=tag)
        check("packs 304", 304, code)
    else:
        check("packs ETag present", True, False)
    for path in ("/v1/providers", "/v1/models", "/v1/guide/curl",
                 "/api/v1/matrix", "/api/v1/health",
                 "/guides", "/signin", "/report"):
        code, _, _ = req(path, TOKEN)
        check("%s 200" % path, 200, code)
    code, body, _ = req("/", TOKEN)
    check("/ table + unassigned",
          True, b"<table>" in body and b"diagnostics.unassigned" in body)
    code, _, _ = req("/feedback", TOKEN, method="POST",
                      data=b'{"provider":"smoke"}')
    check("feedback bad 422", 422, code)
    code, _, _ = req("/feedback", TOKEN, method="POST", data=json.dumps(
        {"provider": "smoke", "model": "smoke", "errorClass": "unknown",
         "httpStatus": 500, "keeperPackVersion": "v2"}).encode())
    check("feedback good 202", 202, code)

NEXT = os.environ.get("KEEPER_TOKEN_NEXT", "")
if NEXT:
    code, _, _ = req("/packs", NEXT)
    check("packs NEXT 200", 200, code)

OLD = os.environ.get("KEEPER_TOKEN_OLD", "")
if OLD:
    code, _, _ = req("/packs", OLD)
    check("packs OLD revoked 401", 401, code)

code, _, _ = req("/packs", "wrong-bearer-smoke")
check("packs wrong 401", 401, code)

if FAIL:
    print("SMOKE RED: %d failing" % len(FAIL), flush=True)
    sys.exit(1)
print("SMOKE GREEN", flush=True)
