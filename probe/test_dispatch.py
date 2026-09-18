#!/usr/bin/env python3
"""dispatch skip tests — keyless placeholder routes are never probed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dispatch import is_placeholder  # noqa: E402


class PlaceholderSkipTest(unittest.TestCase):
    def test_keyless_is_placeholder(self):
        self.assertTrue(is_placeholder({"provider": "zen", "model": "retired-1"}))
        self.assertTrue(is_placeholder({"provider": "zen", "model": "x", "api_key": ""}))

    def test_keyed_is_not_placeholder(self):
        self.assertFalse(is_placeholder(
            {"provider": "openrouter", "model": "m", "api_key": "k"}))


if __name__ == "__main__":
    unittest.main()
