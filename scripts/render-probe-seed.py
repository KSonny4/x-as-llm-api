#!/usr/bin/env python3
"""render-probe-seed.py — keyround receipts -> keeper/probe-seed.json.

Boot baseline for keeper probe_detail: the heartbeat verdicts count as
probes (owner-confirmed 2026-09-20), so redeploys no longer amnesia the
matrix back to all-unknown. Live dual-probe ingest overwrites these
entries; sqlite (same-alloc restarts) overlays them at boot.

Provenance is explicit: every record carries
detail={l1: heartbeat|heartbeat-fail, l2: not-run, source: keyround}.
Key NAMES only — values never enter this pipeline.
"""
import glob
import json
import os
import sys

RECEIPT_GLOB = "docs/zen-egress-receipts/keyround-*.txt"

KEY_TO_CONN = {
    "OPENCODE_ZEN_API_KEY": "zen/pool-spare",
    "OPENCODE_ZEN_API_KEY_PETR": "zen/pool-petr",
    **{"OPENCODE_ZEN_RETIRED_%d" % n: "zen/pool-%d" % n
       for n in range(1, 9)},
}


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


def build_seed(verdicts):
    last = {}
    for v in verdicts:
        last[v["key_name"]] = v
    seed = {}
    for key, v in last.items():
        cid = KEY_TO_CONN.get(key)
        if not cid:
            continue
        ok = bool(v.get("working"))
        seed[cid] = {
            "provider": "opencode-zen", "model": "big-pickle",
            "state": "ok" if ok else "down",
            "detail": {"l1": "heartbeat" if ok else "heartbeat-fail",
                       "l2": "not-run", "source": "keyround",
                       "key_name": key,
                       "mismatch": bool(v.get("mismatch")),
                       "zencli": v.get("zencli"),
                       "opencode": v.get("opencode")},
            "checked_at": v.get("checked_at", "")}
    return seed


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    seed = build_seed(load_verdicts(root))
    out = os.path.join(root, "keeper", "probe-seed.json")
    with open(out, "w") as fh:
        json.dump(seed, fh, indent=1)
        fh.write("\n")
    print("seed %s connections=%d" % (out, len(seed)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
