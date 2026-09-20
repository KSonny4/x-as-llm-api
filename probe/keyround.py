#!/usr/bin/env python3
"""keyround.py — one-key zenCLI test round with opencode-direct fallback.

Per key K (value via env ZEN_KEY_VALUE only — never argv, never logs):
  1. stage {"opencode": {"type": "api", "key": K}} into the CLI auth path
  2. start zencli server, POST echo prompt (WORKING = 200 + expected text)
  3. on zencli fail: run `opencode run` direct with the same staged key,
     record both verdicts (their disagreement = M4 mismatch signal)

Stdout: one verdict JSON line (key NAME only, never the value).
Secrets: env only. Exit 2 on missing/empty/placeholder key (fail closed).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ECHO_MODEL = os.environ.get("KEYROUND_MODEL", "big-pickle")
# All free models on one key per round: the key is working if AT LEAST
# ONE model answers (per-model quota buckets differ). Override with a
# comma list for tests/single-model pins.
DEFAULT_MODELS = ("big-pickle,ling-3.0-flash-fin-free,mimo-v2.5-free,"
                  "muse-spark-1.2-contributor-free,"
                  "muse-spark-1.3-contributor-free,"
                  "nemotron-3-ultra-free,nemotron-3.5-lightning-free,"
                  "jev-1.13-free")
MODELS = [m.strip() for m in
          os.environ.get("KEYROUND_MODELS", DEFAULT_MODELS).split(",")
          if m.strip()]
ECHO_PROMPT = os.environ.get("KEYROUND_PROMPT",
                             "Reply with exactly: KEYROUND-ALIVE")
ECHO_EXPECTED = os.environ.get("KEYROUND_EXPECTED", "KEYROUND-ALIVE")
SERVER_PORT = int(os.environ.get("KEYROUND_PORT", "8099"))
ZENCLI_BIN = os.environ.get("ZENCLI_BIN", "/srv/zencli/zencli")
OPENCODE_BIN = os.environ.get("OPENCODE_BIN",
                               "/root/.opencode/bin/opencode")
CLI_TIMEOUT = int(os.environ.get("KEYROUND_CLI_TIMEOUT", "120"))


def fail(msg):
    sys.stderr.write("keyround refusing: %s\n" % msg)
    raise SystemExit(2)


def key_value():
    v = (os.environ.get("ZEN_KEY_VALUE") or "").strip()
    if not v or v == "{}":
        fail("ZEN_KEY_VALUE missing, empty, or placeholder {}")
    return v


def eligible_names():
    """Keys due for testing per the live keeper queue (None = queue
    unreachable: fall back to the full pool, never to nothing)."""
    token = (os.environ.get("KEYROUND_KEEPER_TOKEN") or "").strip()
    if not token:
        return None
    base = (os.environ.get("KEYROUND_KEEPER_URL",
                            "https://keeper.pkubelka.cz")).rstrip("/")
    req = urllib.request.Request(
        base + "/api/v1/key-queue",
        headers={"User-Agent": "keeper-keyround/1.0",
                 "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            doc = json.loads(res.read().decode("utf-8", "replace"))
    except Exception as e:
        sys.stderr.write("keyround eligibility fetch failed: %s\n" % e)
        return None
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = []
    for k in doc.get("keys", []):
        if k.get("state") == "testing":
            continue
        nxt = k.get("next_test")
        if nxt and nxt > now:
            continue
        out.append(k.get("name"))
    return out


def pick_key():
    """Returns (name, value, conn). Explicit KEYROUND_KEY wins (manual
dispatch); else random pool pick (healthy-pool sampling; pool curation
— enter on pass, backoff on fail — lives in the keeper publish layer,
which sees verdict history; the task stays stateless)."""
    import random as _random
    import time as _time
    only = (os.environ.get("KEYROUND_KEY") or "").strip()
    raw = (os.environ.get("KEYS_JSON") or "").strip()
    if only:
        if not raw:
            fail("KEYROUND_KEY set but KEYS_JSON missing")
        for e in json.loads(raw):
            if e.get("name") == only:
                return only, e.get("value", ""), e.get("conn", "")
        fail("KEYROUND_KEY %s not in KEYS_JSON" % only)
    if not raw:
        # legacy single-key mode
        name = os.environ.get("KEYROUND_KEY_NAME", "")
        if not name:
            fail("KEYROUND_KEY_NAME missing")
        return name, key_value(), ""
    entries = json.loads(raw)
    if not entries:
        fail("empty key pool")
    due = eligible_names()
    if due is not None:
        entries = [e for e in entries if e.get("name") in set(due)]
        if not entries:
            sys.stderr.write("keyround: nothing due, pool idle\n")
            raise SystemExit(0)
    e = _random.SystemRandom().choice(entries)
    return e.get("name", ""), e.get("value", ""), e.get("conn", "")


def jitter_sleep():
    """Loose-cadence jitter: sleep 0..JITTER_SECS before the round so
firings never burst in lockstep. 0 (tests) disables."""
    import time as _time
    cap = int(os.environ.get("KEYROUND_JITTER_SECS", "600"))
    if cap > 0:
        _time.sleep(_random_sleep(cap))


def _random_sleep(cap):
    import random as _random
    return _random.SystemRandom().randint(0, cap)


def retry_hint(text):
    """Best-effort vendor reset hint from error text (estimate, not a
promise): seconds until retry when the vendor says so."""
    import re
    if not text:
        return None
    m = re.search(r"retry[^\d]{0,20}(\d+)\s*(second|minute|hour)",
                  text, re.IGNORECASE)
    if m:
        mul = {"second": 1, "minute": 60, "hour": 3600}
        return int(m.group(1)) * mul[m.group(2).lower()]
    m = re.search(r"try again in (\d+)\s*(second|minute|hour)s?",
                  text, re.IGNORECASE)
    if m:
        mul = {"second": 1, "minute": 60, "hour": 3600}
        return int(m.group(1)) * mul[m.group(2).lower()]
    return None


def stage_key(value, home):
    d = os.path.join(home, ".local", "share", "opencode")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "auth.json")
    with open(p, "w") as fh:
        json.dump({"opencode": {"type": "api", "key": value}}, fh)
    os.chmod(p, 0o600)
    return p


def wait_port(port, tries=30):
    import socket
    for _ in range(tries):
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=2)
            s.close()
            return True
        except OSError:
            time.sleep(1)
    return False


def zencli_start(server_cmd, port, home, start_timeout=30):
    """Start the server (one per round, shared by all model POSTs).
    HOME is forced to the staged dir: without it the server's opencode
    child runs keyless and the vendor 200s anonymously, proving nothing
    about the key (field incident 2026-09-20: bogus key verified ok)."""
    env = dict(os.environ)
    env["HOME"] = home
    proc = subprocess.Popen(
        server_cmd + ["-port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env)
    if not wait_port(port, start_timeout):
        proc.terminate()
        return None
    return proc


def zencli_post(port, model, prompt):
    """One echo POST against a running server. Returns (ok, text)."""
    payload = json.dumps(
        {"model": model,
         "messages": [{"role": "user", "content": prompt}],
         "stream": False}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % port, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=CLI_TIMEOUT) as res:
            doc = json.loads(res.read().decode("utf-8", "replace"))
        text = (doc.get("choices", [{}])[0].get("message", {})
                .get("content", ""))
        ok = res.status == 200 and ECHO_EXPECTED in (text or "")
        return ok, (text or "")[:500]
    except Exception as e:
        return False, "zencli upstream: %s" % e


def zencli_echo(server_cmd, port, model, prompt, home,
                start_timeout=30):
    """Single-model round (legacy path): start, POST, stop."""
    proc = zencli_start(server_cmd, port, home, start_timeout)
    if proc is None:
        return False, "zencli server never listened"
    try:
        return zencli_post(port, model, prompt)
    finally:
        proc.terminate()


def opencode_echo(cli_bin, model, prompt, home):
    """Direct `opencode run` with staged auth. Returns (ok, text)."""
    env = dict(os.environ)
    env["HOME"] = home
    ref = model if "/" in model else "opencode/" + model
    try:
        p = subprocess.run(
            [cli_bin, "run", "--pure", "-m", ref, prompt],
            capture_output=True, text=True, timeout=CLI_TIMEOUT, env=env)
    except Exception as e:
        return False, "exec-fail: %s" % e
    out = (p.stdout or "").strip()
    ok = p.returncode == 0 and ECHO_EXPECTED in out
    if not ok and not out:
        out = "stderr: %s rc=%d" % ((p.stderr or "").strip()[:400],
                                    p.returncode)
    return ok, out[:500]


def run_round(key_name, value, home, server_cmd, cli_bin,
            models=None):
    """One full round over every free model. Returns the verdict dict
    (no secret values). Key is working if AT LEAST ONE model answers."""
    stage_key(value, home)
    models = models if models is not None else MODELS
    proc = zencli_start(server_cmd, SERVER_PORT, home)
    per_model = {}
    try:
        for model in models:
            if proc is None:
                z_ok, z_text = False, "zencli server never listened"
            else:
                z_ok, z_text = zencli_post(SERVER_PORT, model,
                                           ECHO_PROMPT)
            o_ok, o_text = None, None
            if not z_ok:
                o_ok, o_text = opencode_echo(cli_bin, model,
                                             ECHO_PROMPT, home)
            per_model[model] = {
                "zencli": {"ok": z_ok, "text": z_text},
                "opencode": ({"ok": o_ok, "text": o_text}
                             if o_ok is not None else None),
                "mismatch": (o_ok is not None and z_ok != o_ok)}
    finally:
        if proc is not None:
            proc.terminate()
    working = any(m["zencli"]["ok"] for m in per_model.values())
    hint = None
    for m in per_model.values():
        hint = hint or retry_hint(
            None if m["zencli"]["ok"] else m["zencli"]["text"])
        if m["opencode"]:
            hint = hint or retry_hint(m["opencode"]["text"])
    first = per_model.get(ECHO_MODEL, {})
    return {"key_name": key_name,
            "model": ECHO_MODEL,
            "models": per_model,
            "models_ok": sum(1 for m in per_model.values()
                              if m["zencli"]["ok"]),
            "models_total": len(per_model),
            "zencli": first.get("zencli", {"ok": False, "text": ""}),
            "opencode": first.get("opencode"),
            "mismatch": first.get("mismatch", False),
            "working": working,
            "retry_hint_secs": hint,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                        time.gmtime())}


def publish_verdict(verdict, conn):
    """Best-effort POST of the round to keeper /api/v1/probe (the
automatic round-to-publication link). Skips silently without conn or
token; never fails the round (stdout verdict is the record)."""
    token = (os.environ.get("KEYROUND_KEEPER_TOKEN") or "").strip()
    if not conn or not token:
        return "skipped"
    base = (os.environ.get("KEYROUND_KEEPER_URL",
                            "https://keeper.pkubelka.cz")).rstrip("/")
    op = verdict.get("opencode") or {}
    l2 = (("pass" if op.get("ok") else "fail") if op else "not-run")
    body = json.dumps({
        "provider": "opencode-zen", "model": verdict.get("model"),
        "state": "ok" if verdict.get("working") else "down",
        "detail": {
            "l1": ("heartbeat" if verdict.get("working")
                     else "heartbeat-fail"),
            "l2": l2, "source": "keyround",
            "key_name": verdict.get("key_name"),
            "mismatch": bool(verdict.get("mismatch")),
            "retry_hint_secs": verdict.get("retry_hint_secs"),
            "models_ok": verdict.get("models_ok"),
            "models_total": verdict.get("models_total"),
            "models": verdict.get("models"),
            "zencli": verdict.get("zencli"),
            "opencode": verdict.get("opencode")},
        "connection_id": conn,
        "checked_at": verdict.get("checked_at", "")}).encode()
    req = urllib.request.Request(
        base + "/api/v1/probe", data=body,
        headers={"Content-Type": "application/json",
                 # Cloudflare 403s default library UAs (Python-urllib);
                 # browser-like UA required (cognee-memory precedent).
                 "User-Agent": "keeper-keyround/1.0",
                 "Authorization": "Bearer " + token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return "posted:%d" % res.status
    except Exception as e:
        sys.stderr.write("keyround publish failed: %s\n" % e)
        return "failed"


def main(argv):
    if not (os.environ.get("KEYROUND_KEY") or "").strip():
        jitter_sleep()  # pool mode only: manual pins run immediately
    name, value, conn = pick_key()
    if not value or not str(value).strip() or str(value).strip() == "{}":
        fail("picked key %s has no usable value" % name)
    home = os.environ.get("KEYROUND_HOME") or tempfile.mkdtemp(
        prefix="keyround-")
    verdict = run_round(name, value, home,
                        [ZENCLI_BIN], OPENCODE_BIN)
    print(json.dumps(verdict))
    sys.stderr.write("keyround publish: %s\n"
                     % publish_verdict(verdict, conn))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
