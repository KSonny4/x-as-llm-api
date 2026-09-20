#!/usr/bin/env python3
"""zen-send.py — send requests to opencode zen without the full CLI.

Status: SCAFFOLD. Single-request chat is vendor-denied (FreeTierError);
the CLI performs a multi-step flow (bootstrap on models.opencode.ai +
opencode.ai) that this script does not yet replicate. Everything below
the HOLE marker is proven against the vendor (endpoints, exact id.ts
id format, header set); the HOLE is filled by scout findings.

Usage:
  python3 scripts/zen-send.py --model big-pickle --prompt "hi" [--key-file ...]
Secrets: key read from a file path (default laptop opencode auth.json),
never printed, never logged. Values stay in-process.
"""
import argparse
import json
import secrets
import string
import sys
import time
import urllib.request

B62 = string.ascii_letters + string.digits
ZEN = "https://opencode.ai/zen/v1"
UA = ("opencode/1.18.31 ai-sdk/provider-utils/4.0.40 runtime/bun/1.3.14 "
      "pi-opencode-direct/0.1.6")


def mkid(prefix):
    """Exact id.ts ascending format: low 6 bytes of ms*0x1000+1, hex,
    plus 14 random base62. Verified against packages/opencode/src/id/id.ts."""
    now = ((int(time.time() * 1000) * 0x1000 + 1) & 0xFFFFFFFFFFFF)
    return prefix + now.to_bytes(6, "big").hex() + "".join(
        secrets.choice(B62) for _ in range(14))


def key_from_auth_file(path):
    doc = json.load(open(path))
    for section in ("opencode", "opencode-zen-free", "opencode-go"):
        entry = doc.get(section)
        if isinstance(entry, dict) and entry.get("key"):
            return entry["key"]
    raise SystemExit("no usable key section in %s" % path)


def headers(key, session, request):
    return {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "User-Agent": UA,
        "x-opencode-client": "cli",
        "x-opencode-project": "global",
        "x-opencode-session": session,
        "x-opencode-request": request,
        "x-client-request-id": session,
        "HTTP-Referer": "https://opencode.ai/",
        "X-Title": "opencode",
    }


def post(path, key, session, request, body):
    req = urllib.request.Request(
        ZEN + path, data=json.dumps(body).encode(),
        headers=headers(key, session, request), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()[:500]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]


# ---------------------------------------------------------------- HOLE ----
# The CLI's first flights (observed via scripts/mitm-log.py):
#   1. models.opencode.ai:443 (~339KB down — catalog/bootstrap?)
#   2. opencode.ai:443 (session-bound chat payload)
# Single chat POSTs without step 1 fail (FreeTierError / upstream 500).
# Fill in: the exact bootstrap call(s) and what token/context they yield
# for step 2 (scout: cli-flow + console-surface findings go here).
# ---------------------------------------------------------------- HOLE ----


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="big-pickle")
    ap.add_argument("--prompt", default="hi")
    ap.add_argument("--key-file",
                    default="/Users/ksonny/.local/share/opencode/auth.json")
    args = ap.parse_args()
    key = key_from_auth_file(args.key_file)
    session, request = mkid("ses_"), mkid("msg_")
    print("HOLE-NOT-FILLED: bootstrap step unknown; "
          "sending bare chat to show the gate verdict")
    status, body = post("/chat/completions", key, session, request, {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
    })
    print("status:", status)
    print(body)


if __name__ == "__main__":
    main()
