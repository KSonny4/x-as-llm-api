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
    def test_coding_only(self):
        scores = parse_scores(FIXTURE)
        self.assertEqual(scores, {"m-high": 90.0, "m-low": 50.0})

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
        self.assertEqual(scores, {"m-v2": 81.6})


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


def test_conservative_matching_and_rank():
    from aa import rank_models, score_for
    assert score_for({'a': 99}, 'p', 'vendor/a') is None
    assert score_for({'a': float('nan')}, 'p', 'a') is None
    assert score_for({'a': True}, 'p', 'a') is None
    rows = [{'id': 'p-a', 'provider': 'p', 'model': 'a', 'working_keys': 0},
            {'id': 'q-a', 'provider': 'q', 'model': 'a', 'working_keys': 1},
            {'id': 'p-b', 'provider': 'p', 'model': 'b', 'working_keys': 1}]
    assert [r['id'] for r in rank_models(rows, {'a': 90})] == ['q-a', 'p-b', 'p-a']


def test_daily_cache_no_refresh_from_catalog(tmp_path):
    import aa
    from test_api_v2 import state_for, call
    state, _ = state_for(tmp_path)
    state['aa_api_key'] = 'synthetic-aa'
    state['aa_cache'] = str(tmp_path / 'aa.json')
    with patch('aa.urlopen', return_value=FetchTest.Resp(FIXTURE)) as fetch:
        aa.refresh_state(state, now=1800000000)
        aa.refresh_state(state, now=1800000001)
        call(state, 'GET', '/api/v2/catalog')
        assert fetch.call_count == 1
    with patch('aa.urlopen', side_effect=OSError('secret-must-not-leak')):
        aa.refresh_state(state, now=1800086401)
    assert state['aa_stale'] and state['aa_scores']['m-high'] == 90


def test_reviewed_exact_provider_aliases_without_family_or_setting_guesses():
    from aa import score_for
    scores={'ling-3-0-flash-fin':55.6,'nemotron-3-5-lightning':26.8,
            'muse-spark-1-3':75.8,'muse-spark-1-3-xhigh':76.5,'mimo-v2-5-0424':56.8}
    assert score_for(scores,'opencode-zen','ling-3.0-flash-fin-free')==55.6
    assert score_for(scores,'opencode-zen','nemotron-3.5-lightning-free')==26.8
    for provider in ('openrouter','kilocode'):
        assert score_for(scores,provider,'inclusionai/ling-3.0-flash-fin:free')==55.6
        assert score_for(scores,provider,'nvidia/nemotron-3.5-lightning:free')==26.8
    assert score_for(scores,'other','ling-3.0-flash-fin-free') is None
    assert score_for(scores,'opencode-zen','muse-spark-1.3-contributor-free') is None
    assert score_for(scores,'opencode-zen','mimo-v2.5-free') is None


def test_additional_primary_named_aliases_never_guess_reasoning_variants():
    from aa import score_for
    scores={'ling-3-0-flash-vl':57,'inkling-small':52.9,'north-mini-code':36.5,'lfm2-5-2-6b':7.7,'step-3-7-flash':39.6,
            'qwen3-8-27b-xhigh':68.1,'glm-5-2':68.8,'inkling':52.1}
    for provider in ('openrouter','kilocode'):
        for model,score in [('inclusionai/ling-3.0-flash-vl:free',57),('thinkingmachines/inkling-small:free',52.9),('cohere/north-mini-code:free',36.5),('liquid/lfm-2.5-2.6b:free',7.7)]:
            assert score_for(scores,provider,model)==score
        for model in ('qwen/qwen3.8-27b:free','z-ai/glm-5.2:free','thinkingmachines/inkling:free'):
            assert score_for(scores,provider,model) is None
    assert score_for(scores,'kilocode','stepfun/step-3.7-flash:free')==39.6
