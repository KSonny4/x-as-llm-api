#!/usr/bin/env python3
"""keyround tests — fake zencli server + fake opencode binary, no vendor."""
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import keyround


def fake_opencode(tmp, text, marker):
    """Deployment-faithful fake: consults $HOME/.local/share/opencode/
auth.json like the real binary (missing file or wrong key fails).
The right key arrives via FAKE_EXPECTED_KEY env."""
    p = os.path.join(tmp, "opencode")
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\n"
                 "echo \"x\" > \"%s\"\n" % marker +
                 "KEY=$(python3 -c \"import json,os;"
                 "print(json.load(open(os.environ['HOME']+"
                 "'/.local/share/opencode/auth.json'))"
                 "['opencode']['key'])\" 2>/dev/null)\n"
                 "if [ \"$KEY\" != \"$FAKE_EXPECTED_KEY\" ]; then\n"
                 "  echo 'Invalid API key.' >&2\n"
                 "  exit 1\n"
                 "fi\n"
                 "echo '%s'\n" % text)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


STUB_SERVER = '''
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
OK = (sys.argv[1] == "ok")
MARKER = sys.argv[2]
PORT = int(sys.argv[sys.argv.index("-port") + 1])
# Deployment-faithful: the stub consults the staged key like the real
# opencode child would (proves HOME plumbing delivers it).
try:
    staged = json.load(open(os.environ["HOME"] +
        "/.local/share/opencode/auth.json"))["opencode"]["key"]
except Exception:
    staged = None
KEY_OK = (staged is not None
          and staged == os.environ.get("FAKE_EXPECTED_KEY"))
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        self.rfile.read(ln)
        open(MARKER, "w").write("zencli-ran HOME=" +
                                  os.environ.get("HOME", ""))
        good = OK and KEY_OK
        raw = (json.dumps({"choices": [{"message": {
            "content": "KEYROUND-ALIVE"}}]}).encode() if good
               else b\'{"error": "Invalid API key."}\')
        self.send_response(200 if good else 403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
'''


class RoundTest(unittest.TestCase):
    def run_round_e2e(self, tmp, zen_ok, value="sekret",
                      expected="sekret"):
        stub = os.path.join(tmp, "stub_zencli.py")
        with open(stub, "w") as fh:
            fh.write(STUB_SERVER)
        zmark = os.path.join(tmp, "zmark")
        omark = os.path.join(tmp, "omark")
        import sys as _sys
        port = 18000 + (abs(hash(tmp)) % 2000)
        keyround.SERVER_PORT = port
        old = os.environ.get("FAKE_EXPECTED_KEY")
        os.environ["FAKE_EXPECTED_KEY"] = expected
        try:
            v = keyround.run_round(
                "K1", value, tmp,
                [_sys.executable, stub, "ok" if zen_ok else "no",
                 zmark],
                fake_opencode(tmp, "KEYROUND-ALIVE", omark))
        finally:
            if old is None:
                del os.environ["FAKE_EXPECTED_KEY"]
            else:
                os.environ["FAKE_EXPECTED_KEY"] = old
        return v, port, zmark

    def test_working_no_fallback(self):
        tmp = tempfile.mkdtemp()
        v, _, zmark = self.run_round_e2e(tmp, True)
        self.assertTrue(v["working"])
        self.assertTrue(v["zencli"]["ok"])
        self.assertIsNone(v["opencode"])
        self.assertFalse(v["mismatch"])
        self.assertNotIn("sekret", json.dumps(v))
        with open(zmark) as fh:
            self.assertIn("HOME=" + tmp, fh.read())

    def test_bogus_key_fails_both_legs(self):
        # Regression: 2026-09-20 keyless server 200'd a bogus key.
        # Both legs must consult the staged key now.
        tmp = tempfile.mkdtemp()
        v, _, _ = self.run_round_e2e(tmp, True, value="bogus",
                                      expected="sekret")
        self.assertFalse(v["working"])
        self.assertFalse(v["zencli"]["ok"])
        self.assertIsNotNone(v["opencode"])
        self.assertFalse(v["opencode"]["ok"])
        self.assertFalse(v["mismatch"])

    def test_fallback_mismatch(self):
        tmp = tempfile.mkdtemp()
        v, _, _ = self.run_round_e2e(tmp, False)
        self.assertFalse(v["working"])
        self.assertFalse(v["zencli"]["ok"])
        self.assertTrue(v["opencode"]["ok"])
        self.assertTrue(v["mismatch"])

    def test_verdict_shape(self):
        v = {"key_name": "K9", "model": keyround.ECHO_MODEL,
             "zencli": {"ok": False, "text": "x"},
             "opencode": {"ok": True, "text": "KEYROUND-ALIVE"},
             "mismatch": True, "working": False,
             "retry_hint_secs": None, "checked_at": "t"}
        for k in ("key_name", "model", "zencli", "opencode",
                  "mismatch", "working", "retry_hint_secs",
                  "checked_at"):
            self.assertIn(k, v)
        s = json.dumps(v)
        self.assertNotIn("sekret", s)

    def test_key_refusals(self):
        for bad in (None, "", "  ", "{}"):
            env = {"PATH": os.environ.get("PATH", "")}
            if bad is not None:
                env["ZEN_KEY_VALUE"] = bad
            old = dict(os.environ)
            os.environ.clear()
            os.environ.update(env)
            try:
                with self.assertRaises(SystemExit) as cm:
                    keyround.key_value()
                self.assertEqual(cm.exception.code, 2)
            finally:
                os.environ.clear()
                os.environ.update(old)

    def test_stage_key_format(self):
        tmp = tempfile.mkdtemp()
        p = keyround.stage_key("sekret", tmp)
        with open(p) as fh:
            doc = json.load(fh)
        self.assertEqual(doc,
                         {"opencode": {"type": "api", "key": "sekret"}})
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")

    def test_opencode_echo_ok(self):
        tmp = tempfile.mkdtemp()
        marker = os.path.join(tmp, "ran")
        cli = fake_opencode(tmp, "KEYROUND-ALIVE", marker)
        ok, text = keyround.opencode_echo(cli, "big-pickle", "hi", tmp)
        self.assertTrue(ok)
        self.assertIn("KEYROUND-ALIVE", text)

    def test_opencode_echo_fail_keeps_evidence(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "opencode")
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\necho boom >&2\nexit 3\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        ok, text = keyround.opencode_echo(p, "big-pickle", "hi", tmp)
        self.assertFalse(ok)
        self.assertIn("rc=3", text)



class PoolTest(unittest.TestCase):
    KEYS = ('[{"name": "A", "value": "va", "conn": "zen/a"}, '
            '{"name": "B", "value": "vb", "conn": "zen/b"}]')

    def _env(self, **kw):
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update({"PATH": old.get("PATH", ""),
                           "KEYROUND_JITTER_SECS": "0"})
        os.environ.update(kw)
        return old

    def _restore(self, old):
        os.environ.clear()
        os.environ.update(old)

    def test_pool_pick_membership(self):
        old = self._env(KEYS_JSON=self.KEYS)
        try:
            seen = {keyround.pick_key() for _ in range(20)}
            self.assertTrue({s[0] for s in seen} <= {"A", "B"})
            self.assertTrue(all(s[2].startswith("zen/") for s in seen))
        finally:
            self._restore(old)

    def test_explicit_key_wins(self):
        old = self._env(KEYS_JSON=self.KEYS, KEYROUND_KEY="B")
        try:
            self.assertEqual(keyround.pick_key(), ("B", "vb", "zen/b"))
        finally:
            self._restore(old)

    def test_unknown_key_fails_closed(self):
        old = self._env(KEYS_JSON=self.KEYS, KEYROUND_KEY="Z")
        try:
            with self.assertRaises(SystemExit) as cm:
                keyround.pick_key()
            self.assertEqual(cm.exception.code, 2)
        finally:
            self._restore(old)

    def test_empty_pool_fails_closed(self):
        old = self._env(KEYS_JSON="[]")
        try:
            with self.assertRaises(SystemExit) as cm:
                keyround.pick_key()
            self.assertEqual(cm.exception.code, 2)
        finally:
            self._restore(old)

    def test_jitter_disabled_at_zero(self):
        old = self._env(KEYROUND_JITTER_SECS="0")
        try:
            import time as _t
            t0 = _t.time()
            keyround.jitter_sleep()
            self.assertLess(_t.time() - t0, 1)
        finally:
            self._restore(old)

    def test_retry_hint(self):
        self.assertEqual(
            keyround.retry_hint("retry in 30 seconds"), 30)
        self.assertEqual(
            keyround.retry_hint("try again in 2 minutes"), 120)
        self.assertEqual(
            keyround.retry_hint("Rate limit exceeded."), None)
        self.assertIsNone(keyround.retry_hint(""))
        self.assertIsNone(keyround.retry_hint(None))



class PublishTest(unittest.TestCase):
    def verdict(self, working=True):
        return {"key_name": "K1", "model": "big-pickle",
                "zencli": {"ok": working, "text": "t"},
                "opencode": None, "mismatch": False, "working": working,
                "retry_hint_secs": None,
                "checked_at": "2026-09-20T15:23:20Z"}

    def _env(self, **kw):
        old = dict(os.environ)
        for k in ("KEYROUND_KEEPER_TOKEN", "KEYROUND_KEEPER_URL"):
            os.environ.pop(k, None)
        os.environ.update(kw)
        return old

    def _restore(self, old):
        for k in ("KEYROUND_KEEPER_TOKEN", "KEYROUND_KEEPER_URL"):
            os.environ.pop(k, None)
        for k, v in old.items():
            if k in ("KEYROUND_KEEPER_TOKEN", "KEYROUND_KEEPER_URL"):
                os.environ[k] = v

    def test_skipped_without_token_or_conn(self):
        old = self._env()
        try:
            self.assertEqual(
                keyround.publish_verdict(self.verdict(), "zen/a"),
                "skipped")
            os.environ["KEYROUND_KEEPER_TOKEN"] = "t"
            self.assertEqual(
                keyround.publish_verdict(self.verdict(), ""), "skipped")
        finally:
            self._restore(old)

    def test_posts_probe_shape(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                ln = int(self.headers.get("Content-Length", 0))
                seen["auth"] = self.headers.get("Authorization")
                seen["doc"] = json.loads(self.rfile.read(ln))
                raw = b'{"ok": true}'
                self.send_response(202)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        srv = HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        old = self._env(KEYROUND_KEEPER_TOKEN="sekret-tok",
                        KEYROUND_KEEPER_URL="http://127.0.0.1:%d" % port)
        try:
            self.assertEqual(
                keyround.publish_verdict(self.verdict(), "zen/a"),
                "posted:202")
        finally:
            self._restore(old)
            srv.shutdown()
        self.assertEqual(seen["auth"], "Bearer sekret-tok")
        doc = seen["doc"]
        self.assertEqual(doc["connection_id"], "zen/a")
        self.assertEqual(doc["state"], "ok")
        self.assertEqual(doc["detail"]["l1"], "heartbeat")
        self.assertEqual(doc["detail"]["source"], "keyround")
        self.assertNotIn("sekret", json.dumps(doc).replace(
            "sekret-tok", ""))

if __name__ == "__main__":
    unittest.main()
