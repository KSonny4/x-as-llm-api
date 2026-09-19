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
GEMINI_GEN = json.dumps({"candidates": [{"content": {"parts": [
    {"text": "pong"}]}}]})


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

    def test_l1_ok_gemini(self):
        srv = make_stub({"/v1beta/models/gemini-2.5-flash:generateContent":
                         (200, GEMINI_GEN)})
        try:
            out, _, fb = self.probe_l1(self.route(
                f"http://127.0.0.1:{srv.server_port}", wire="gemini",
                model="gemini-2.5-flash"))
            self.assertEqual(out, "ok")
            self.assertIsNone(fb)
        finally:
            srv.shutdown()

    def test_l1_gemini_401_is_suspect_with_auth_feedback(self):
        srv = make_stub({"/v1beta/models/gemini-2.5-flash:generateContent":
                         (401, '{"error":{"message":"bad key"}}')})
        try:
            out, _, fb = self.probe_l1(self.route(
                f"http://127.0.0.1:{srv.server_port}", wire="gemini",
                model="gemini-2.5-flash"))
            self.assertEqual(out, "suspect")
            self.assertEqual(fb["errorClass"], "auth")
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

    def test_l2_ref_overrides_cli_model_ref(self):
        self.set_cli("#!/bin/sh\necho \"ref=$4\"\n")
        ok, text = self.probe_l2(
            dict(self.route("http://x", model="big-pickle",
                            provider="opencode-zen"),
                 l2_ref="opencode/big-pickle"), env=self.env)
        self.assertTrue(ok)
        self.assertIn("ref=opencode/big-pickle", text)

    def test_l2_fail_keeps_stderr_evidence(self):
        self.set_cli("#!/bin/sh\necho boom >&2\nexit 1\n")
        ok, text = self.probe_l2(self.route("http://x", model="p/m"),
                                 env=self.env)
        self.assertFalse(ok)
        self.assertIn("boom", text)
        self.assertIn("rc=1", text)

    def test_cli_slot_acquire_release(self):
        from worker import _cli_slot
        d = os.path.join(self.tmp, "slots")
        with _cli_slot(limit=2, timeout=5, slot_dir=d):
            self.assertEqual(os.listdir(d), [str(os.getpid())])
        self.assertEqual(os.listdir(d), [])

    def test_cli_slot_reaps_dead_holders(self):
        from worker import _cli_slot
        d = os.path.join(self.tmp, "slots")
        os.makedirs(d)
        open(os.path.join(d, "999999999"), "w").close()
        with _cli_slot(limit=1, timeout=5, slot_dir=d):
            self.assertIn(str(os.getpid()), os.listdir(d))
            self.assertNotIn("999999999", os.listdir(d))

    def test_cli_slot_limit_blocks(self):
        from worker import _cli_slot
        d = os.path.join(self.tmp, "slots")
        os.makedirs(d)
        open(os.path.join(d, str(os.getppid())), "w").close()
        live = [f for f in os.listdir(d) if f.isdigit()]
        self.assertEqual(len(live), 1)  # parent pid holds the only slot
        with self.assertRaises(TimeoutError):
            with _cli_slot(limit=1, timeout=1, slot_dir=d):
                pass

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


class DispatchTest(unittest.TestCase):
    """dispatch.py posts probe results to keeper (stub both sides)."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.cli_path = os.path.join(self.bin, "opencode")
        self.set_cli("#!/bin/sh\necho pong\n")

    def set_cli(self, script):
        with open(self.cli_path, "w") as f:
            f.write(script)
        os.chmod(self.cli_path, os.stat(self.cli_path).st_mode | stat.S_IEXEC)

    def test_reports_ok_route_and_posts(self):
        import dispatch
        srv = make_stub({"/models": (200, OPENAI_MODELS),
                         "/chat/completions": (200, OPENAI_CHAT)})
        posted = []

        import urllib.request as urlreq
        real_urlopen = urlreq.urlopen

        class Resp:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=15):
            if req.full_url.startswith("http://127.0.0.1:9"):
                posted.append(json.loads(req.data.decode()))
                return Resp()
            return real_urlopen(req, timeout=timeout)

        urlreq.urlopen = fake_urlopen
        old = dict(os.environ)
        old_path = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = self.bin + ":" + old_path
            self.set_cli("#!/bin/sh\necho pong\n")
            os.environ["SEEDS_JSON"] = json.dumps({"routes": [{
                "provider": "p", "model": "muse",
                "base_url": f"http://127.0.0.1:{srv.server_port}",
                "wire": "openai", "api_key": "k",
                "connection_id": "p/muse", "active": True}]})
            os.environ["KEEPER_URL"] = "http://127.0.0.1:9"
            os.environ["KEEPER_TOKEN"] = "t"
            self.assertEqual(dispatch.main(), 0)
        finally:
            urlreq.urlopen = real_urlopen
            os.environ.clear()
            os.environ.update(old)
            srv.shutdown()
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["state"], "ok")
        self.assertEqual(posted[0]["model"], "muse")

    def test_refuses_without_token(self):
        import dispatch
        old = dict(os.environ)
        try:
            os.environ["SEEDS_JSON"] = '{"routes": []}'
            os.environ.pop("KEEPER_TOKEN", None)
            self.assertEqual(dispatch.main(), 1)
        finally:
            os.environ.clear()
            os.environ.update(old)


class FleetUATest(unittest.TestCase):
    def test_get_and_post_send_fleet_ua(self):
        import worker
        seen = {}

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{}'

        import urllib.request as urlreq
        real = urlreq.urlopen

        def fake(req, timeout=10):
            seen[req.full_url] = req.get_header('User-agent')
            return Resp()

        urlreq.urlopen = fake
        try:
            route = {"base_url": "http://127.0.0.1:9", "api_key": "k"}
            worker._get(route, "/models")
            worker._post(route, "/chat", {})
        finally:
            urlreq.urlopen = real
        self.assertEqual(seen["http://127.0.0.1:9/models"], worker.FLEET_UA)
        self.assertEqual(seen["http://127.0.0.1:9/chat"], worker.FLEET_UA)
        self.assertTrue(worker.FLEET_UA.startswith("keeper-probe/"))


if __name__ == "__main__":
    unittest.main()
