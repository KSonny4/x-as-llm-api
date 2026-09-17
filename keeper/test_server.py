#!/usr/bin/env python3
"""L1 skeleton tests: healthz, bearer discipline, 404s. Hermetic (no sockets)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server


class HealthTest(unittest.TestCase):
    def test_healthz_contract_exists(self):
        self.assertTrue(hasattr(server, "H"))

    def test_healthz_needs_no_auth(self):
        code, body, _ = server.route("GET", "/healthz", {}, "test-token")
        self.assertEqual(code, 200)
        self.assertEqual(body, b"ok")

    def test_unknown_path_is_404_even_authed(self):
        code, _, _ = server.route("GET", "/nope", {"authorization": "Bearer t"}, "t")
        self.assertEqual(code, 404)

    def test_protected_path_requires_bearer(self):
        for headers in ({}, {"authorization": "Bearer wrong"}):
            code, _, _ = server.route("GET", "/packs", headers, "right")
            self.assertEqual(code, 401, headers)


class TokenTest(unittest.TestCase):
    def test_refuses_empty_token(self):
        with self.assertRaises(SystemExit):
            server.require_token("")


if __name__ == "__main__":
    unittest.main()
