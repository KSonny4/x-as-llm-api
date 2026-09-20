#!/usr/bin/env python3
"""render-keyqueue.py — keyround receipts -> keeper/keyqueue.json ledger.

Reads verdict JSON lines from docs/zen-egress-receipts/keyround-*.txt
(plus --testing names for in-flight rounds) and emits the pool ledger:
per key {name, state, zencli, opencode, mismatch, retry_hint_secs,
checked_at, consecutive_dead, next_test}.

States: pending (never tested), testing (--testing flag), ok (last
working), dead (last not working). Backoff: next_test = last + 2^dead
hours (cap 24h); ok keys retest hourly (heartbeat). Recovery is a plain
ok verdict after dead — the flip itself is the "available again" event.
Key NAMES only — values never enter this pipeline.
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

POOL = ["OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_API_KEY_PETR",
        "OPENCODE_ZEN_RETIRED_1", "OPENCODE_ZEN_RETIRED_2",
        "OPENCODE_ZEN_RETIRED_3", "OPENCODE_ZEN_RETIRED_4",
        "OPENCODE_ZEN_RETIRED_5", "OPENCODE_ZEN_RETIRED_6",
        "OPENCODE_ZEN_RETIRED_7", "OPENCODE_ZEN_RETIRED_8"]

RECEIPT_GLOB = "docs/zen-egress-receipts/keyround-*.txt"


def parse_time(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def load_verdicts(root):
    out = []
    for path in sorted(glob.glob(os.path.join(root, RECEIPT_GLOB))):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                if "key_name" in doc and "working" in doc:
                    out.append(doc)
    return out


def build_ledger(verdicts, testing=(), now=None):
    now = now or datetime.now(timezone.utc)
    by_key = {}
    for v in verdicts:
        by_key.setdefault(v["key_name"], []).append(v)
    keys = []
    for name in POOL:
        hist = sorted(by_key.get(name, []),
                      key=lambda v: v.get("checked_at", ""))
        last = hist[-1] if hist else None
        dead = 0
        for v in reversed(hist):
            if v.get("working"):
                break
            dead += 1
        if name in set(testing):
            state = "testing"
        elif last is None:
            state = "pending"
        elif last.get("working"):
            state = "ok"
        else:
            state = "dead"
        if last and parse_time(last.get("checked_at")):
            gap = min(2 ** dead, 24) if dead else 1
            nxt = (parse_time(last["checked_at"]) +
                   timedelta(hours=gap)).strftime("%Y-%m-%dT%H:%M:%SZ")
            checked = last["checked_at"]
        else:
            nxt, checked = None, None
        keys.append({
            "name": name, "state": state,
            "zencli": (last or {}).get("zencli"),
            "opencode": (last or {}).get("opencode"),
            "mismatch": (last or {}).get("mismatch"),
            "retry_hint_secs": (last or {}).get("retry_hint_secs"),
            "models_ok": (last or {}).get("models_ok"),
            "models_total": (last or {}).get("models_total"),
            "models": (last or {}).get("models"),
            "checked_at": checked, "consecutive_dead": dead,
            "next_test": nxt})
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "keys": keys}


def live_queue(base, token):
    """Merged queue view from a live keeper (names+verdicts, no values).
    Lets renders capture auto-published rounds that never touched a
    receipt file (field gap 2026-09-20: pool-3's ok died with an alloc)."""
    import urllib.request
    req = urllib.request.Request(
        base.rstrip("/") + "/api/v1/key-queue",
        headers={"User-Agent": "keeper-keyround/1.0",
                 "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as res:
        doc = json.load(res)
    if not (isinstance(doc, dict) and isinstance(doc.get("keys"), list)):
        raise ValueError("bad live queue shape")
    return doc


def live_verdicts(doc):
    """Live queue entries back into verdict-shaped dicts for build_ledger
    (history merge: live lines behave like the newest receipt lines)."""
    out = []
    for k in doc.get("keys", []):
        if not k.get("checked_at"):
            continue
        out.append({
            "key_name": k.get("name"), "model": "big-pickle",
            "models": k.get("models"),
            "models_ok": k.get("models_ok"),
            "models_total": k.get("models_total"),
            "zencli": k.get("zencli"), "opencode": k.get("opencode"),
            "mismatch": bool(k.get("mismatch")),
            "working": k.get("state") == "ok",
            "retry_hint_secs": k.get("retry_hint_secs"),
            "checked_at": k.get("checked_at")})
    return out


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    testing = [a for a in argv[2:] if not a.startswith("--")]
    live = [a.split("=", 1)[1] for a in argv[2:]
            if a.startswith("--live=")]
    verdicts = load_verdicts(root)
    if live:
        token = os.environ.get("KEEPER_TOKEN", "")
        if not token:
            print("live requested without KEEPER_TOKEN env")
            return 2
        verdicts = verdicts + live_verdicts(live_queue(live[0], token))
    ledger = build_ledger(verdicts, testing)
    out = os.path.join(root, "keeper", "keyqueue.json")
    with open(out, "w") as fh:
        json.dump(ledger, fh, indent=1)
        fh.write("\n")
    states = {}
    for k in ledger["keys"]:
        states[k["state"]] = states.get(k["state"], 0) + 1
    print("ledger %s states=%s" % (out, states))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
