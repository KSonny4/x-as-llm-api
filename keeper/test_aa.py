"""AA snapshot fetch (tiebreak input only). Fixture-tested, stdlib only.

Snapshot via ARTIFICIALANALYSIS_API_KEY, file cache, last-good retained:
failure -> cached scores + stale=True; no cache -> empty + stale=True.
Scores index models; AA orders quality ties among probe-ok models only.
"""
import json
import os
import unittest
from unittest.mock import patch

from aa import fetch_snapshot, parse_scores

FIXTURE = {"data": [
    {"id": "m-high", "coding": 90.0, "intelligence": 70.0},
    {"id": "m-low", "coding": 50.0},
    {"id": "m-brain", "intelligence": 80.0},
    {"id": "m-none"},
]}


class ParseTest(unittest.TestCase):
    def test_prefers_coding_then_intelligence(self):
        scores = parse_scores(FIXTURE)
        self.assertEqual(scores, {"m-high": 90.0, "m-low": 50.0, "m-brain": 80.0})

    def test_prefers_slug_over_uuid_id(self):
        scores = parse_scores({"data": [
            {"id": "3e87c73e-uuid", "slug": "gpt-4o-mini", "coding": 77.0},
            {"id": "plain-id", "coding": 11.0},
        ]})
        self.assertEqual(scores, {"gpt-4o-mini": 77.0, "plain-id": 11.0})

    def test_v2_evaluations_coding_index_first(self):
        scores = parse_scores({"data": [{
            "id": "uuid-1", "slug": "m-v2",
            "evaluations": {
                "artificial_analysis_coding_index": 81.6,
                "artificial_analysis_intelligence_index": 53.4}},
            {"id": "uuid-2", "slug": "m-intel",
             "evaluations": {
                 "artificial_analysis_coding_index": None,
                 "artificial_analysis_intelligence_index": 53.4}},
        ]})
        self.assertEqual(scores, {"m-v2": 81.6, "m-intel": 53.4})


class FetchTest(unittest.TestCase):
    def _cache(self, tmp=True):
        import tempfile
        d = tempfile.mkdtemp()
        return os.path.join(d, "aa.json")

    class Resp:
        def __init__(self, payload):
            self._payload = payload
        def read(self):
            return json.dumps(self._payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def test_success_writes_cache_not_stale(self):
        cache = self._cache()
        with patch("aa.urlopen", return_value=self.Resp(FIXTURE)):
            scores, stale = fetch_snapshot("KEY", cache)
        self.assertEqual(scores["m-high"], 90.0)
        self.assertFalse(stale)
        self.assertTrue(os.path.exists(cache))

    def test_uses_x_api_key_header(self):
        seen = {}

        class Cap(self.Resp):
            pass

        def fake(req, timeout=20):
            seen["x-api-key"] = req.get_header("X-api-key")
            seen["authorization"] = req.get_header("Authorization")
            return self.Resp(FIXTURE)

        with patch("aa.urlopen", side_effect=fake):
            fetch_snapshot("KEY", self._cache())
        self.assertEqual(seen["x-api-key"], "KEY")
        self.assertIsNone(seen["authorization"])

    def test_failure_serves_last_good_stale(self):
        cache = self._cache()
        with patch("aa.urlopen", return_value=self.Resp(FIXTURE)):
            fetch_snapshot("KEY", cache)
        with patch("aa.urlopen", side_effect=OSError("down")):
            scores, stale = fetch_snapshot("KEY", cache)
        self.assertEqual(scores["m-high"], 90.0)
        self.assertTrue(stale)

    def test_failure_without_cache_is_empty_stale(self):
        cache = os.path.join("/nonexistent-dir-xyz", "aa.json")
        with patch("aa.urlopen", side_effect=OSError("down")):
            scores, stale = fetch_snapshot("KEY", cache)
        self.assertEqual(scores, {})
        self.assertTrue(stale)


if __name__ == "__main__":
    unittest.main()
