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
    p = os.path.join(tmp, "opencode")
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\necho '%s' > '%s'\necho '%s'\n"
                 % (marker, marker, text))
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


STUB_SERVER = '''
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
OK = (sys.argv[1] == "ok")
MARKER = sys.argv[2]
PORT = int(sys.argv[sys.argv.index("-port") + 1])
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        self.rfile.read(ln)
        open(MARKER, "w").write("zencli-ran")
        raw = (json.dumps({"choices": [{"message": {
            "content": "KEYROUND-ALIVE"}}]}).encode() if OK
               else b\'{"error": "denied"}\')
        self.send_response(200 if OK else 403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
'''


class RoundTest(unittest.TestCase):
    def run_round_e2e(self, tmp, zen_ok):
        stub = os.path.join(tmp, "stub_zencli.py")
        with open(stub, "w") as fh:
            fh.write(STUB_SERVER)
        zmark = os.path.join(tmp, "zmark")
        omark = os.path.join(tmp, "omark")
        import sys as _sys
        port = 18000 + (abs(hash(tmp)) % 2000)
        keyround.SERVER_PORT = port
        return keyround.run_round(
            "K1", "sekret", tmp,
            [_sys.executable, stub, "ok" if zen_ok else "no",
             zmark],
            fake_opencode(tmp, "KEYROUND-ALIVE", omark)), port

    def test_working_no_fallback(self):
        tmp = tempfile.mkdtemp()
        v, _ = self.run_round_e2e(tmp, True)
        self.assertTrue(v["working"])
        self.assertTrue(v["zencli"]["ok"])
        self.assertIsNone(v["opencode"])
        self.assertFalse(v["mismatch"])
        self.assertNotIn("sekret", json.dumps(v))

    def test_fallback_mismatch(self):
        tmp = tempfile.mkdtemp()
        v, _ = self.run_round_e2e(tmp, False)
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
    KEYS = '[{"name": "A", "value": "va"}, {"name": "B", "value": "vb"}]'

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
            seen = {keyround.pick_key()[0] for _ in range(20)}
            self.assertTrue(seen <= {"A", "B"})
        finally:
            self._restore(old)

    def test_explicit_key_wins(self):
        old = self._env(KEYS_JSON=self.KEYS, KEYROUND_KEY="B")
        try:
            self.assertEqual(keyround.pick_key(), ("B", "vb"))
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


if __name__ == "__main__":
    unittest.main()
