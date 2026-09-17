#!/usr/bin/env python3
"""L4 probe worker tests — stubs only, no live calls, no real CLI."""
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_stub(behavior):
    """behavior: dict path -> (code, body). Special: 'chat_code' etc. via paths."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            raw = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path in behavior:
                code, body = behavior[self.path]
                return self._send(code, body)
            return self._send(404, '{"error":{"message":"not found"}}')

        def do_POST(self):
            if self.path in behavior:
                code, body = behavior[self.path]
                return self._send(code, body)
            return self._send(404, '{"error":{"message":"not found"}}')
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


OPENAI_MODELS = '{"data":[{"id":"muse"}]}'
OPENAI_CHAT = '{"choices":[{"message":{"content":"pong"}}]}'
ANTHROPIC_MSG = '{"content":[{"text":"pong"}]}'


class ProbeTest(unittest.TestCase):
    def setUp(self):
        from worker import probe_l1, probe_l2, probe_route, write_status  # noqa
        self.probe_l1 = probe_l1
        self.probe_l2 = probe_l2
        self.probe_route = probe_route
        self.write_status = write_status
        self.tmp = tempfile.mkdtemp()
        # stubbed opencode CLI on PATH
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.cli_path = os.path.join(self.bin, "opencode")
        with open(self.cli_path, "w") as f:
            f.write("#!/bin/sh\necho stub-no-behavior\n")
        os.chmod(self.cli_path, os.stat(self.cli_path).st_mode | stat.S_IEXEC)
        self.env = dict(os.environ, PATH=self.bin + ":" + os.environ.get("PATH", ""))

    def set_cli(self, script):
        with open(self.cli_path, "w") as f:
            f.write(script)
        os.chmod(self.cli_path, os.stat(self.cli_path).st_mode | stat.S_IEXEC)

    def route(self, base, wire="openai", model="muse", provider="p"):
        return {"base_url": base, "wire": wire, "model": model,
                "provider": provider, "api_key": "test-key"}

    def test_l1_ok_openai(self):
        srv = make_stub({"/models": (200, OPENAI_MODELS),
                         "/chat/completions": (200, OPENAI_CHAT)})
        try:
            out, detail, fb = self.probe_l1(self.route(f"http://127.0.0.1:{srv.server_port}"))
            self.assertEqual(out, "ok")
            self.assertIsNone(fb)
        finally:
            srv.shutdown()

    def test_l1_ok_anthropic(self):
        srv = make_stub({"/models": (200, OPENAI_MODELS),
                         "/v1/messages": (200, ANTHROPIC_MSG)})
        try:
            out, _, fb = self.probe_l1(self.route(
                f"http://127.0.0.1:{srv.server_port}", wire="anthropic"))
            self.assertEqual(out, "ok")
            self.assertIsNone(fb)
        finally:
            srv.shutdown()

    def test_l1_conn_refused_is_suspect(self):
        out, detail, fb = self.probe_l1(self.route("http://127.0.0.1:1"))
        self.assertEqual(out, "suspect")
        self.assertTrue(detail)

    def test_l1_429_is_limited_with_backoff(self):
        srv = make_stub({"/models": (429, '{"error":{"message":"rate limited"}}')})
        try:
            out, detail, fb = self.probe_l1(self.route(f"http://127.0.0.1:{srv.server_port}"))
            self.assertEqual(out, "limited")
            self.assertIn("backoff_at", detail)
        finally:
            srv.shutdown()

    def test_l1_401_is_suspect_with_feedback(self):
        srv = make_stub({"/models": (401, '{"error":{"message":"unauthorized"}}')})
        try:
            out, _, fb = self.probe_l1(self.route(f"http://127.0.0.1:{srv.server_port}"))
            self.assertEqual(out, "suspect")
            self.assertIsNotNone(fb)
            self.assertEqual(fb["httpStatus"], 401)
        finally:
            srv.shutdown()

    def test_l1_wrong_wire_is_misconfigured(self):
        srv = make_stub({"/models": (200, OPENAI_MODELS),
                         "/chat/completions": (404, '{"error":{"type":"not_found"}}')})
        try:
            out, _, _ = self.probe_l1(self.route(f"http://127.0.0.1:{srv.server_port}"))
            self.assertEqual(out, "misconfigured")
        finally:
            srv.shutdown()

    def test_l2_pass_means_degraded(self):
        self.set_cli("#!/bin/sh\necho pong\n")
        ok, text = self.probe_l2(self.route("http://x", model="p/m"), env=self.env)
        self.assertTrue(ok)
        state = self.probe_route(self.route("http://127.0.0.1:1", model="p/m"),
                                 l2env=self.env)["state"]
        self.assertEqual(state, "degraded")

    def test_l2_fail_means_down(self):
        self.set_cli("#!/bin/sh\necho boom >&2\nexit 1\n")
        state = self.probe_route(self.route("http://127.0.0.1:1", model="p/m"),
                                 l2env=self.env)["state"]
        self.assertEqual(state, "down")

    def test_report_flips_suspect_and_status_json(self):
        r = self.route("http://127.0.0.1:1", model="p/m")
        res = self.probe_route(r, report={"reason": "user"}, l2env=self.env)
        self.assertEqual(res["state"], "suspect")
        path = os.path.join(self.tmp, "status.json")
        self.write_status(path, [res])
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved["routes"][0]["state"], "suspect")


if __name__ == "__main__":
    unittest.main()
