#!/usr/bin/env python3
"""tripwire negative controls — the scanner must catch planted secrets
and spare known-safe shapes. Runs tripwire.sh against a temp root
(TRIPWIRE_ROOT) so fixtures never touch the repo."""
import os
import subprocess
import tempfile
import unittest

TRIPWIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "tripwire.sh")
# Fixtures are assembled at runtime so the test file itself stays
# tripwire-clean (no secret-shaped literals in git).
HEXKEY = "9f" * 32
SKVAL = "sk-" + "abcdefghij" + "1234567890"
JWT = ("eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0In0."
       "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw")


class TripwireNegatives(unittest.TestCase):
    def scan(self, files):
        tmp = tempfile.mkdtemp()
        for name, content in files.items():
            p = os.path.join(tmp, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(content)
        env = dict(os.environ, TRIPWIRE_ROOT=tmp)
        p = subprocess.run(["bash", TRIPWIRE], capture_output=True,
                           text=True, env=env)
        return p.returncode, p.stdout

    def test_hex_key_fires(self):
        code, _ = self.scan({"k.txt": "key = \"%s\"\n" % HEXKEY})
        self.assertEqual(code, 1)

    def test_key_on_sha256_labelled_line_fires(self):
        code, _ = self.scan({"k.txt": "{\"sha256\": \"%s\"}\n" % HEXKEY})
        self.assertEqual(code, 1)

    def test_sk_value_fires(self):
        code, _ = self.scan({"k.txt": "x = \"%s\"\n" % SKVAL})
        self.assertEqual(code, 1)

    def test_jwt_fires(self):
        code, _ = self.scan({"k.txt": "tok=%s\n" % JWT})
        self.assertEqual(code, 1)

    def test_model_slug_silent(self):
        code, _ = self.scan({"k.txt": "path: openrouter/openrouter/bodybuilder\n"
                             "model: cognitivecomputations/dolphin-mistral-24b-venice-edition\n"})
        self.assertEqual(code, 0)

    def test_git_sha_silent(self):
        code, _ = self.scan({"k.txt": "revision: a5e74112e423024744108ed9314fd26b779dd5ce\n"})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
