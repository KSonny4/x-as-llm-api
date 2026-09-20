#!/usr/bin/env python3
"""render-keyqueue tests — pure ledger logic, no vendor, no cluster."""
import os
import sys
import unittest
from datetime import datetime, timezone

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "render_keyqueue",
    os.path.join(os.path.dirname(__file__), "render-keyqueue.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_ledger = _mod.build_ledger


def v(name, working, ts, mismatch=False, hint=None):
    return {"key_name": name, "model": "big-pickle",
            "zencli": {"ok": working, "text": "t"},
            "opencode": None, "mismatch": mismatch, "working": working,
            "retry_hint_secs": hint, "checked_at": ts}


NOW = datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc)


class LedgerTest(unittest.TestCase):
    def test_pending_without_verdicts(self):
        led = build_ledger([], now=NOW)
        self.assertEqual(len(led["keys"]), 10)
        for k in led["keys"]:
            self.assertEqual(k["state"], "pending")
            self.assertIsNone(k["next_test"])

    def test_ok_and_next_test_hourly(self):
        led = build_ledger(
            [v("OPENCODE_ZEN_RETIRED_1", True, "2026-09-20T15:23:20Z")],
            now=NOW)
        k = [x for x in led["keys"]
             if x["name"] == "OPENCODE_ZEN_RETIRED_1"][0]
        self.assertEqual(k["state"], "ok")
        self.assertEqual(k["consecutive_dead"], 0)
        self.assertEqual(k["next_test"], "2026-09-20T16:23:20Z")

    def test_dead_backoff(self):
        led = build_ledger(
            [v("OPENCODE_ZEN_RETIRED_2", False, "2026-09-20T12:00:00Z"),
             v("OPENCODE_ZEN_RETIRED_2", False, "2026-09-20T14:00:00Z")],
            now=NOW)
        k = [x for x in led["keys"]
             if x["name"] == "OPENCODE_ZEN_RETIRED_2"][0]
        self.assertEqual(k["state"], "dead")
        self.assertEqual(k["consecutive_dead"], 2)
        self.assertEqual(k["next_test"], "2026-09-20T18:00:00Z")

    def test_recovery_resets_dead(self):
        led = build_ledger(
            [v("OPENCODE_ZEN_RETIRED_3", False, "2026-09-20T12:00:00Z"),
             v("OPENCODE_ZEN_RETIRED_3", True, "2026-09-20T15:00:00Z")],
            now=NOW)
        k = [x for x in led["keys"]
             if x["name"] == "OPENCODE_ZEN_RETIRED_3"][0]
        self.assertEqual(k["state"], "ok")
        self.assertEqual(k["consecutive_dead"], 0)

    def test_testing_flag(self):
        led = build_ledger([], testing=["OPENCODE_ZEN_RETIRED_4"],
                           now=NOW)
        k = [x for x in led["keys"]
             if x["name"] == "OPENCODE_ZEN_RETIRED_4"][0]
        self.assertEqual(k["state"], "testing")

    def test_live_verdicts_shape(self):
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "rk", "render-keyqueue.py")
        rk = _ilu.module_from_spec(spec)
        spec.loader.exec_module(rk)
        out = rk.live_verdicts({"keys": [
            {"name": "A", "state": "ok", "zencli": {"ok": True},
             "opencode": None, "mismatch": False,
             "retry_hint_secs": None, "models_ok": 7, "models_total": 8,
             "models": {"m": {}}, "checked_at": "2026-09-20T17:00:00Z"},
            {"name": "B", "state": "pending", "checked_at": None}]})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["working"])
        self.assertEqual(out[0]["models_ok"], 7)

    def test_no_secret_values(self):
        import json
        led = build_ledger(
            [v("OPENCODE_ZEN_RETIRED_1", True, "2026-09-20T15:23:20Z")],
            now=NOW)
        self.assertNotIn("sk-", json.dumps(led))


if __name__ == "__main__":
    unittest.main()
