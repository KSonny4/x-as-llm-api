#!/usr/bin/env python3
"""Inventory tests: live enumeration, cache, per-provider degradation.
Hermetic: inventory.urlopen is stubbed in every test (no live calls)."""
import json
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import inventory


OPENAI_PAYLOAD = {"data": [{"id": "b-model"}, {"id": "a-model"}]}
GEMINI_PAYLOAD = {"models": [{"name": "models/gemini-x"},
                             {"name": "models/gemini-a"}]}

ROUTES = [
    {"provider": "openrouter", "model": "openai/seed-only",
     "base_url": "https://openrouter.ai/api/v1", "api_key": "k1",
     "wire": "openai"},
    {"provider": "gemini", "model": "gemini-seed",
     "base_url": "https://generativelanguage.googleapis.com",
     "api_key": "k2", "wire": "gemini"},
]


class FakeResp:
    def __init__(self, doc):
        self._raw = json.dumps(doc).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class InventoryCase(unittest.TestCase):
    def setUp(self):
        inventory.clear_cache()
        self._urlopen = inventory.urlopen
        self.calls = []

    def tearDown(self):
        inventory.urlopen = self._urlopen
        inventory.clear_cache()

    def stub(self, mapping):
        """mapping: url-substring -> payload-dict or Exception instance."""
        def fake(req, timeout=15):
            url = req.full_url
            self.calls.append(url)
            for key, value in mapping.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return FakeResp(value)
            raise AssertionError("unstubbed URL " + url)
        inventory.urlopen = fake

    def test_openai_parser_and_request_shape(self):
        seen = {}

        def fake(req, timeout=15):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            return FakeResp(OPENAI_PAYLOAD)
        inventory.urlopen = fake
        out = inventory.openai_compatible_models(
            "https://openrouter.ai/api/v1/", "k1")
        self.assertEqual(out, ["a-model", "b-model"])
        self.assertEqual(seen["url"],
                         "https://openrouter.ai/api/v1/models")
        self.assertEqual(seen["auth"], "Bearer k1")

    def test_gemini_parser_strips_prefix(self):
        self.stub({"generativelanguage": GEMINI_PAYLOAD})
        out = inventory.gemini_models("k2")
        self.assertEqual(out, ["gemini-a", "gemini-x"])

    def test_union_lists_seed_models(self):
        self.stub({"openrouter": OPENAI_PAYLOAD,
                   "generativelanguage": GEMINI_PAYLOAD})
        out = inventory.get_inventory(self.routes())
        self.assertIn("openai/seed-only", out["openrouter"])
        self.assertIn("a-model", out["openrouter"])
        self.assertIn("gemini-seed", out["gemini"])

    def routes(self):
        return [dict(r) for r in ROUTES]

    def test_cache_hit_skips_http(self):
        self.stub({"openrouter": OPENAI_PAYLOAD,
                   "generativelanguage": GEMINI_PAYLOAD})
        inventory.get_inventory(self.routes())
        first = len(self.calls)
        self.assertGreater(first, 0)
        inventory.get_inventory(self.routes())
        self.assertEqual(len(self.calls), first)

    def test_refresh_bypasses_cache(self):
        self.stub({"openrouter": OPENAI_PAYLOAD,
                   "generativelanguage": GEMINI_PAYLOAD})
        inventory.get_inventory(self.routes())
        first = len(self.calls)
        inventory.get_inventory(self.routes(), refresh=True)
        self.assertGreater(len(self.calls), first)

    def test_failing_provider_degrades_others_resolve(self):
        self.stub({"openrouter": OPENAI_PAYLOAD,
                   "generativelanguage": urllib.error.URLError("down")})
        out = inventory.get_inventory(self.routes())
        self.assertEqual(out["gemini"], ["gemini-seed"])
        self.assertIn("a-model", out["openrouter"])

    def test_unknown_wire_lists_seed_only(self):
        routes = [{"provider": "weird", "model": "weird-m",
                   "base_url": "https://weird.example",
                   "api_key": "k", "wire": "bespoke"}]
        self.stub({})
        out = inventory.get_inventory(routes)
        self.assertEqual(out, {"weird": ["weird-m"]})
        self.assertEqual(self.calls, [])

    def test_no_live_http_in_suite(self):
        self.stub({"openrouter": OPENAI_PAYLOAD,
                   "generativelanguage": GEMINI_PAYLOAD})
        inventory.get_inventory(self.routes())
        inventory.get_inventory(self.routes(), refresh=True)
        for url in self.calls:
            self.assertTrue(url.startswith("https://openrouter.ai")
                            or "generativelanguage" in url, url)


if __name__ == "__main__":
    unittest.main()
