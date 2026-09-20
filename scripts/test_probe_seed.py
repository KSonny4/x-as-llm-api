#!/usr/bin/env python3
"""render-probe-seed tests — mapping + provenance, no vendor."""
import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "render_probe_seed",
    os.path.join(os.path.dirname(__file__), "render-probe-seed.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def v(name, working, ts):
    return {"key_name": name, "model": "big-pickle",
            "zencli": {"ok": working, "text": "t"},
            "opencode": None, "mismatch": False, "working": working,
            "retry_hint_secs": None, "checked_at": ts}


class SeedTest(unittest.TestCase):
    def test_key_to_connection(self):
        seed = _mod.build_seed(
            [v("OPENCODE_ZEN_RETIRED_1", True, "2026-09-20T15:23:20Z"),
             v("OPENCODE_ZEN_API_KEY", True, "2026-09-20T15:28:28Z")])
        self.assertEqual(set(seed),
                         {"zen/retired-1", "zen/big-pickle-spare"})
        r = seed["zen/retired-1"]
        self.assertEqual(r["state"], "ok")
        self.assertEqual(r["provider"], "opencode-zen")
        self.assertEqual(r["detail"]["l1"], "heartbeat")
        self.assertEqual(r["detail"]["source"], "keyround")

    def test_dead_maps_down(self):
        seed = _mod.build_seed(
            [v("OPENCODE_ZEN_RETIRED_2", False, "2026-09-20T12:00:00Z")])
        self.assertEqual(seed["zen/retired-2"]["state"], "down")

    def test_last_verdict_wins(self):
        seed = _mod.build_seed(
            [v("OPENCODE_ZEN_RETIRED_3", False, "2026-09-20T12:00:00Z"),
             v("OPENCODE_ZEN_RETIRED_3", True, "2026-09-20T15:00:00Z")])
        self.assertEqual(seed["zen/retired-3"]["state"], "ok")

    def test_unknown_key_skipped(self):
        self.assertEqual(_mod.build_seed(
            [v("SOME_OTHER_KEY", True, "2026-09-20T15:00:00Z")]), {})


if __name__ == "__main__":
    unittest.main()
