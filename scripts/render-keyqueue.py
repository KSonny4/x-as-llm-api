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


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    testing = argv[2:]
    ledger = build_ledger(load_verdicts(root), testing)
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
