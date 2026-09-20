#!/usr/bin/env python3
"""Wave-2 route tests: L1 discipline + packs/feedback/dispenser/chat/route/
matrix/pages. Hermetic: seed fixtures inline, upstream stubbed, tmp paths.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server


SEED = {"routes": [
    {"provider": "acme-openai", "model": "acme-chat",
     "base_url": "https://acme.example/v1", "api_key": "k1",
     "wire": "openai", "env_var": "ACME_KEY",
     "owner": "Owner <owner@example.com>", "name": "Acme Chat",
     "connection_id": "c1", "active": True},
    {"provider": "acme-anthropic", "model": "acme-claude",
     "base_url": "https://acme.example", "api_key": "k2",
     "wire": "anthropic", "env_var": "ACME_CLAUDE_KEY",
     "owner": "owner@example.com", "name": "Acme Claude",
     "connection_id": "c2", "active": True},
    {"provider": "acme-pending", "model": "acme-waiting",
     "base_url": "https://acme.example", "wire": "openai",
     "env_var": "ACME_WAITING_KEY", "owner": "",
     "name": "Acme Waiting", "connection_id": "c3", "active": True},
]}

OPENAI_UPSTREAM = {"id": "chatcmpl-1", "object": "chat.completion",
                   "created": 0, "model": "acme-chat",
                   "choices": [{"index": 0,
                                "message": {"role": "assistant",
                                            "content": "hi"},
                                "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 1,
                             "total_tokens": 4}}

ANTHROPIC_UPSTREAM = {"id": "msg_1", "model": "acme-claude",
                      "role": "assistant",
                      "content": [{"type": "text", "text": "hello"}],
                      "stop_reason": "end_turn",
                      "usage": {"input_tokens": 5, "output_tokens": 2}}


class FakeResp:
    def __init__(self, status, doc):
        self.status = status
        self._raw = json.dumps(doc).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RouteCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.state = server.make_state(
            "t", SEED, feedback_log=os.path.join(tmp, "fb.jsonl"),
            aa_cache=os.path.join(tmp, "aa.json"))
        self._urlopen = server.urlopen
        self._enumerate = server.enumerate_inventory
        server.enumerate_inventory = lambda routes, refresh=False: {}

    def tearDown(self):
        server.urlopen = self._urlopen
        server.enumerate_inventory = self._enumerate

    def call(self, method, path, headers=None, body=None):
        headers = dict(headers or {})
        if "authorization" not in {k.lower() for k in headers}:
            headers["authorization"] = "Bearer t"
        raw = json.dumps(body).encode() if body is not None else None
        return server.route(method, path, headers, "t", body=raw,
                            state=self.state)

    def stub_upstream(self, doc):
        server.urlopen = lambda req, timeout=30: FakeResp(200, doc)


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


class PacksTest(RouteCase):
    def test_values_served_authed(self):
        code, raw, headers = self.call("GET", "/packs")
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertEqual(doc["keeperPackVersion"], "v2")
        creds = [m["credential"]["value"] for m in doc["packs"]
                 if "credential" in m]
        self.assertIn("k1", creds)
        waiting = [m for m in doc["packs"] if m["model"] == "acme-waiting"]
        self.assertTrue(waiting[0]["signin"]["steps"])
        self.assertEqual(dict(headers).get("Cache-Control"), "no-store, private")

    def test_etag_304(self):
        _, _, headers = self.call("GET", "/packs")
        tag = dict(headers)["ETag"]
        code, _, _ = self.call("GET", "/packs",
                               {"authorization": "Bearer t",
                                "If-None-Match": tag})
        self.assertEqual(code, 304)

    def test_packs_requires_bearer(self):
        code, _, _ = server.route("GET", "/packs", {}, "t",
                                  state=self.state)
        self.assertEqual(code, 401)


class FeedbackTest(RouteCase):
    def good(self):
        return {"provider": "acme-openai", "model": "acme-chat",
                "errorClass": "auth", "httpStatus": 401,
                "keeperPackVersion": "v2"}

    def test_missing_field_422(self):
        doc = self.good()
        del doc["httpStatus"]
        code, raw, _ = self.call("POST", "/feedback", body=doc)
        self.assertEqual(code, 422)
        self.assertEqual(json.loads(raw)["missing"], ["httpStatus"])

    def test_bad_error_class_422(self):
        doc = self.good()
        doc["errorClass"] = "nope"
        code, _, _ = self.call("POST", "/feedback", body=doc)
        self.assertEqual(code, 422)

    def test_valid_spools_202_and_flips_suspect(self):
        code, raw, _ = self.call("POST", "/feedback", body=self.good())
        self.assertEqual(code, 202)
        with open(self.state["feedback_log"], encoding="utf-8") as fh:
            lines = fh.read().strip().split("\n")
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["errorClass"], "auth")
        self.assertEqual(self.state["probe"]["acme-openai/acme-chat"],
                         "suspect")


class DispenserTest(RouteCase):
    def test_providers_shape(self):
        code, raw, _ = self.call("GET", "/v1/providers")
        self.assertEqual(code, 200)
        providers = json.loads(raw)["providers"]
        acme = [p for p in providers if p["provider"] == "acme-openai"][0]
        self.assertEqual(acme["baseURL"], "https://acme.example/v1")
        self.assertEqual(acme["modelIDs"], ["acme-chat"])
        self.assertEqual(acme["envVar"], "ACME_KEY")
        self.assertIn("/v1/chat/completions", acme["curl"])

    def test_guide_one_curl_per_model(self):
        for who in ("curl", "pi", "opencode"):
            code, raw, _ = self.call("GET", "/v1/guide/" + who)
            self.assertEqual(code, 200, who)
            doc = json.loads(raw)
            models = {c["model"] for c in doc["curls"]}
            self.assertIn("acme-chat", models)
            self.assertIn("acme-claude", models)
            for curl in doc["curls"]:
                self.assertIn("/v1/chat/completions", curl["curl"])

    def test_guide_unknown_404(self):
        code, _, _ = self.call("GET", "/v1/guide/smtp")
        self.assertEqual(code, 404)


class ChatTest(RouteCase):
    def test_openai_wire_choices(self):
        self.stub_upstream(OPENAI_UPSTREAM)
        code, raw, _ = self.call("POST", "/v1/chat/completions", body={
            "model": "acme-chat",
            "messages": [{"role": "user", "content": "ping"}]})
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertEqual(doc["choices"][0]["message"]["content"], "hi")

    def test_anthropic_wire_identical_shape(self):
        self.stub_upstream(ANTHROPIC_UPSTREAM)
        code, raw, _ = self.call("POST", "/v1/chat/completions", body={
            "model": "acme-claude",
            "messages": [{"role": "user", "content": "ping"}]})
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertEqual(doc["object"], "chat.completion")
        self.assertEqual(doc["choices"][0]["message"]["content"], "hello")
        self.assertIn("usage", doc)

    def test_stream_yields_sse_chunks(self):
        self.stub_upstream(OPENAI_UPSTREAM)
        code, raw, headers = self.call("POST", "/v1/chat/completions", body={
            "model": "acme-chat",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True})
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn("data: ", text)
        self.assertTrue(text.rstrip().endswith("data: [DONE]"))
        self.assertEqual(dict(headers)["Content-Type"], "text/event-stream")

    def test_unknown_model_404(self):
        code, raw, _ = self.call("POST", "/v1/chat/completions", body={
            "model": "nope", "messages": []})
        self.assertEqual(code, 404)
        self.assertIn("error", json.loads(raw))

    def test_models_lists_seeded(self):
        code, raw, _ = self.call("GET", "/v1/models")
        self.assertEqual(code, 200)
        ids = {m["id"] for m in json.loads(raw)["data"]}
        self.assertEqual(ids, {"acme-chat", "acme-claude", "acme-waiting"})


class RouteEndpointTest(RouteCase):
    def test_route_shape(self):
        code, raw, _ = self.call("GET", "/v1/route/acme-chat")
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertEqual(doc, {
            "model": "acme-chat", "baseURL": "https://acme.example/v1",
            "verification": "unverified_raw_configuration",
            "api": "openai", "auth": {"scheme": "bearer", "value": "k1"},
            "features": ["chat", "stream", "tools"],
            "keeperPackVersion": "v2"})

    def test_route_requires_bearer(self):
        code, _, _ = server.route("GET", "/v1/route/acme-chat", {}, "t",
                                  state=self.state)
        self.assertEqual(code, 401)

    def test_route_unknown_404(self):
        code, _, _ = self.call("GET", "/v1/route/nope")
        self.assertEqual(code, 404)


class MatrixEndpointTest(RouteCase):
    def test_matrix_rows_and_diagnostics(self):
        code, raw, _ = self.call("GET", "/api/v1/matrix")
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertEqual(doc["emails"], ["owner@example.com"])
        self.assertTrue(doc["rows"])
        self.assertIn("unassigned", doc["diagnostics"])
        waiting = doc["diagnostics"]["unassigned"]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["id"], "c3")

    def test_matrix_refresh_bypass(self):
        _, first, _ = self.call("GET", "/api/v1/matrix")
        code, second, _ = self.call("GET", "/api/v1/matrix?refresh=1")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(first)["rows"],
                         json.loads(second)["rows"])

    def test_accounts_and_health(self):
        code, raw, _ = self.call("GET", "/api/v1/accounts")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["emails"], ["owner@example.com"])
        code, raw, _ = self.call("GET", "/api/v1/health")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(raw)["ok"])

    def test_index_html_table_and_unassigned(self):
        code, raw, headers = self.call("GET", "/")
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn("<table id=\"tbl\"", text)
        self.assertIn("owner@example.com", text)
        self.assertIn("diagnostics.unassigned", text)
        self.assertNotIn("k1", text)
        self.assertEqual(dict(headers)["Content-Type"], "text/html")

    def test_keyqueue_endpoint_and_section(self):
        code, raw, _ = self.call("GET", "/api/v1/key-queue")
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertIn("generated_at", doc)
        self.assertIsInstance(doc["keys"], list)
        for k in doc["keys"]:
            self.assertIn(k["state"],
                          ("pending", "testing", "ok", "dead"))
            self.assertNotIn("value", json.dumps(k))
        code, raw, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn('id="keyqueue"', raw.decode())


class PagesTest(RouteCase):
    def test_guides_page(self):
        code, raw, _ = self.call("GET", "/guides")
        self.assertEqual(code, 200)
        self.assertIn("/v1/chat/completions", raw.decode())

    def test_signin_page(self):
        code, raw, _ = self.call("GET", "/signin")
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn("re-mint", text)
        self.assertIn("ACME_WAITING_KEY", text)

    def test_report_page_and_round_trip(self):
        code, raw, _ = self.call("GET", "/report")
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn('action="/feedback"', text)
        self.assertIn("acme-openai/acme-chat", text)
        code, _, _ = self.call("POST", "/feedback", body={
            "provider": "acme-openai", "model": "acme-chat",
            "errorClass": "denied", "httpStatus": 403,
            "keeperPackVersion": "v2"})
        self.assertEqual(code, 202)
        with open(self.state["feedback_log"], encoding="utf-8") as fh:
            self.assertIn("denied", fh.read())


class ParallelAcceptTest(unittest.TestCase):
    """Rotation: route() accepts a tuple of tokens (current + next).
    Single-string call sites keep working unchanged."""
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.state = server.make_state(
            "old", SEED, feedback_log=os.path.join(tmp, "fb.jsonl"),
            aa_cache=os.path.join(tmp, "aa.json"))

    def get(self, bearer, token):
        code, _, _ = server.route(
            "GET", "/packs", {"authorization": bearer}, token,
            state=self.state)
        return code

    def test_tuple_accepts_either_token(self):
        self.assertEqual(self.get("Bearer old", ("old", "new")), 200)
        self.assertEqual(self.get("Bearer new", ("old", "new")), 200)

    def test_tuple_rejects_third_and_empty(self):
        for bearer in ("Bearer other", "", "Bearer "):
            self.assertEqual(self.get(bearer, ("old", "new")), 401)

    def test_empty_next_accepts_only_current(self):
        self.assertEqual(self.get("Bearer old", ("old", "")), 200)
        self.assertEqual(self.get("Bearer new", ("old", "")), 401)

    def test_single_string_unchanged(self):
        self.assertEqual(self.get("Bearer old", "old"), 200)
        self.assertEqual(self.get("Bearer new", "old"), 401)


class MetricsTest(RouteCase):
    SPLIT = {"provider": "zen", "model": "big-pickle",
             "state": "degraded",
             "detail": {"l1": "suspect", "l2": "pong"},
             "checked_at": "2026-09-18T00:00:00+00:00"}
    DOWN = {"provider": "zen", "model": "other",
            "state": "down", "detail": {"l1": "suspect"},
            "checked_at": "2026-09-18T00:00:00+00:00"}

    def get_metrics(self, headers=None, state=None):
        headers = {"authorization": "Bearer t"} if headers is None else headers
        return server.route("GET", "/metrics", headers, "t",
                            state=state or self.state)

    def test_metrics_requires_bearer(self):
        code, _, _ = server.route("GET", "/metrics", {}, "t",
                                  state=self.state)
        self.assertEqual(code, 401)

    def test_divergent_gauge_and_timestamp(self):
        self.state["probe_detail"] = {"zen/big-pickle": self.SPLIT,
                                        "zen/other": self.DOWN}
        code, raw, headers = self.get_metrics()
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn('keeper_route_divergent{provider="zen",'
                      'model="big-pickle",connection="zen/big-pickle"} 1',
                      text)
        self.assertIn('keeper_route_divergent{provider="zen",'
                      'model="other",connection="zen/other"} 0', text)
        self.assertIn("keeper_probe_checked_at_seconds{", text)
        self.assertIn("# TYPE keeper_route_divergent gauge", text)

    def test_down_gauge_mirrors_both_legs_fail(self):
        self.state["probe_detail"] = {"zen/big-pickle": self.SPLIT,
                                        "zen/other": self.DOWN}
        code, raw, _ = self.get_metrics()
        self.assertEqual(code, 200)
        text = raw.decode()
        self.assertIn('keeper_route_down{provider="zen",'
                      'model="other",connection="zen/other"} 1',
                      text)
        self.assertIn('keeper_route_down{provider="zen",'
                      'model="big-pickle",connection="zen/big-pickle"} 0',
                      text)
        self.assertIn("# TYPE keeper_route_down gauge", text)

    def test_empty_detail_exposes_no_series(self):
        code, raw, _ = self.get_metrics()
        self.assertEqual(code, 200)
        self.assertNotIn("keeper_route_divergent{", raw.decode())


class ProbeIngestTest(RouteCase):
    SPLIT = {"provider": "acme-openai", "model": "acme-chat",
             "state": "degraded",
             "detail": {"l1": "suspect", "l2": "pong"},
             "checked_at": "2026-09-18T00:00:00+00:00"}

    def post_probe(self, body, token="Bearer t"):
        raw = json.dumps(body).encode() if body is not None else b"{"
        return server.route("POST", "/api/v1/probe",
                            {"authorization": token}, "t", body=raw,
                            state=self.state)

    def test_ingest_split_lands_in_matrix(self):
        code, raw, _ = self.post_probe(self.SPLIT)
        self.assertEqual(code, 202)
        self.assertEqual(self.state["probe"]["c1"], "degraded")
        self.assertEqual(
            self.state["probe_detail"]["c1"]["detail"]["l1"], "suspect")
        code, raw, _ = self.call("GET", "/api/v1/matrix")
        doc = json.loads(raw)
        self.assertEqual(doc["diagnostics"]["divergent"], ["c1"])

    def test_ingest_rejects_shape(self):
        for bad in (None, {}, {"provider": "acme-openai"},
                    dict(self.SPLIT, state="bogus"),
                    dict(self.SPLIT, model="nope")):
            code, _, _ = self.post_probe(bad)
            self.assertEqual(code, 422, bad)

    def test_ingest_requires_bearer(self):
        code, _, _ = server.route(
            "POST", "/api/v1/probe", {}, "t",
            body=json.dumps(self.SPLIT).encode(), state=self.state)
        self.assertEqual(code, 401)

    def test_ingest_connection_id_targets_one_spare(self):
        self.state["routes"] = list(self.state["routes"]) + [
            {"provider": "acme-openai", "model": "acme-chat",
             "base_url": "https://acme.example/v1", "api_key": "k9",
             "wire": "openai", "env_var": "ACME_KEY_2",
             "owner": "owner@example.com", "name": "Acme Chat spare",
             "connection_id": "c9", "active": True}]
        body = dict(self.SPLIT, state="ok", connection_id="c9",
                    detail={"l1": "ok"})
        code, _, _ = self.post_probe(body)
        self.assertEqual(code, 202)
        self.assertEqual(self.state["probe"]["c9"], "ok")
        self.assertNotIn("c1", self.state["probe"])

    def test_ingest_unknown_connection_rejected(self):
        body = dict(self.SPLIT, connection_id="ghost")
        code, _, _ = self.post_probe(body)
        self.assertEqual(code, 422)

    def test_ingest_legacy_ambiguous_route_requires_exact_id(self):
        self.state["routes"] = list(self.state["routes"]) + [
            {"provider": "acme-openai", "model": "acme-chat",
             "base_url": "https://acme.example/v1", "api_key": "k9",
             "wire": "openai", "env_var": "ACME_KEY_2",
             "owner": "owner@example.com", "name": "Acme Chat spare",
             "connection_id": "c9", "active": True}]
        code, _, _ = self.post_probe(self.SPLIT)
        self.assertEqual(code, 422)
        self.assertNotIn("c1", self.state["probe"])
        self.assertNotIn("c9", self.state["probe"])


class SessionCase(RouteCase):
    """Cookie login: browsers read pages, never mutate state."""

    def mint(self, bearer="Bearer t"):
        return server.route("POST", "/api/v1/session",
                            {"authorization": bearer}, "t",
                            state=self.state)

    def raw_cookie(self, headers):
        for key, value in headers:
            if key == "Set-Cookie":
                return value.split(";", 1)[0].split("=", 1)[1]
        return ""

    def test_login_page_is_public(self):
        code, body, _ = server.route("GET", "/login", {}, "t",
                                     state=self.state)
        self.assertEqual(code, 200)
        self.assertIn(b"<form", body)
        self.assertIn(b"/api/v1/session", body)

    def test_mint_ok_sets_hardened_cookie(self):
        code, body, headers = self.mint()
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"ok": True})
        jar = [v for k, v in headers if k == "Set-Cookie"]
        self.assertEqual(len(jar), 1)
        for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/",
                     "Max-Age=43200"):
            self.assertIn(flag, jar[0])
        self.assertTrue(self.raw_cookie(headers))

    def test_mint_bad_bearer_sets_no_cookie(self):
        for headers in ({}, {"authorization": "Bearer wrong"}):
            code, _, out = self.mint(
                headers.get("authorization", ""))
            self.assertEqual(code, 401, headers)
            self.assertEqual([k for k, _ in out if k == "Set-Cookie"],
                             [])

    def test_mint_requires_bearer_not_cookie(self):
        _, _, headers = self.mint()
        cookie = {"cookie": "keeper_session=" +
                  self.raw_cookie(headers)}
        code, _, _ = server.route("POST", "/api/v1/session", cookie,
                                  "t", state=self.state)
        self.assertEqual(code, 401)

    def test_cookie_gets_page_but_no_mutation(self):
        _, _, headers = self.mint()
        cookie = {"cookie": "keeper_session=" +
                  self.raw_cookie(headers)}
        code, body, _ = server.route("GET", "/", cookie, "t",
                                     state=self.state)
        self.assertEqual(code, 200)
        self.assertIn(b"<table id=\"tbl\"", body)
        code, _, _ = server.route(
            "POST", "/feedback", cookie, "t",
            body=json.dumps({"provider": "x"}).encode(),
            state=self.state)
        self.assertEqual(code, 401)

    def test_unknown_cookie_is_401(self):
        code, _, _ = server.route(
            "GET", "/", {"cookie": "keeper_session=nope"}, "t",
            state=self.state)
        self.assertEqual(code, 401)

    def test_expired_session_is_401(self):
        _, _, headers = self.mint()
        raw = self.raw_cookie(headers)
        digest = server.hashlib.sha256(raw.encode()).hexdigest()
        self.state["sessions"][digest] = 1.0  # long past
        code, _, _ = server.route(
            "GET", "/", {"cookie": "keeper_session=" + raw}, "t",
            state=self.state)
        self.assertEqual(code, 401)
        self.assertNotIn(digest, self.state["sessions"])  # swept

    def test_index_has_live_poller_and_logout(self):
        _, _, headers = self.mint()
        cookie = {"cookie": "keeper_session=" +
                  self.raw_cookie(headers)}
        code, body, _ = server.route("GET", "/", cookie, "t",
                                     state=self.state)
        self.assertEqual(code, 200)
        for needle in (b"/api/v1/matrix?refresh=1",
                       b"setInterval(poll,30000)", b"id=\"stale\"",
                       b"/api/v1/session/logout",
                       b'<meta charset="utf-8">'):
            self.assertIn(needle, body)

    def test_index_shows_divergent_badge_and_checked_at(self):
        self.state["probe_detail"]["c1"] = {
            "provider": "acme-openai", "model": "acme-chat",
            "state": "degraded",
            "detail": {"l1": "suspect", "l2": "pong-text"},
            "checked_at": "2026-09-18T00:00:00+00:00"}
        code, body, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"DIVERGENT", body)
        self.assertIn(b"2026-09-18", body)

    def test_index_escapes_route_names(self):
        out = server._cell_html({"name": "<img src=x>",
                                 "state": "ok"}).encode()
        self.assertNotIn(b"<img", out)
        self.assertIn(b"&lt;img", out)

    def test_logout_clears_and_kills(self):
        _, _, headers = self.mint()
        raw = self.raw_cookie(headers)
        cookie = {"cookie": "keeper_session=" + raw}
        code, _, out = server.route("POST", "/api/v1/session/logout",
                                    dict(cookie), "t", state=self.state)
        self.assertEqual(code, 200)
        jar = [v for k, v in out if k == "Set-Cookie"]
        self.assertTrue(any("Max-Age=0" in v for v in jar))
        code, _, _ = server.route("GET", "/", cookie, "t",
                                  state=self.state)
        self.assertEqual(code, 401)


class PacksPathTest(RouteCase):
    """One standalone pack per model: infinity/<provider>/<model>."""

    def test_every_pack_has_infinity_path(self):
        code, raw, _ = self.call("GET", "/packs")
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertTrue(doc["packs"])
        for pack in doc["packs"]:
            self.assertEqual(pack["path"], "infinity/%s/%s" % (
                pack["provider"], pack["model"]))
            self.assertIsInstance(pack["model"], str)

    def test_route_serves_inventory_packs(self):
        server.enumerate_inventory = lambda routes, refresh=False: \
            {"zen": ["new-model"]}
        code, raw, _ = self.call("GET", "/packs")
        self.assertEqual(code, 200)
        by_path = {p["path"]: p for p in json.loads(raw)["packs"]}
        self.assertIn("infinity/zen/new-model", by_path)
        self.assertIn("signin", by_path["infinity/zen/new-model"])

    def test_inventory_only_models_get_signin_packs(self):
        doc = server.freeze(self.state,
                            {"zen": ["big-pickle", "new-model"]})
        by_path = {p["path"]: p for p in doc["packs"]}
        extra = by_path["infinity/zen/new-model"]
        self.assertEqual(extra["model"], "new-model")
        self.assertIn("signin", extra)
        self.assertNotIn("credential", extra)

    def test_seeded_inventory_model_not_duplicated(self):
        doc = server.freeze(self.state, {"acme-openai": ["acme-chat"]})
        paths = [p["path"] for p in doc["packs"]]
        self.assertEqual(paths.count("infinity/acme-openai/acme-chat"), 1)
        seeded = [p for p in doc["packs"]
                  if p["path"] == "infinity/acme-openai/acme-chat"][0]
        self.assertIn("credential", seeded)


class OpenViewTest(RouteCase):
    """Provider-open view: ok-only columns, AA-desc, display-only.
    The matrix JSON keeps every column in insertion order; only the
    served HTML carries the open-view order + visibility flags."""

    def open_state(self, stale=False):
        routes = [
            {"provider": "p1", "model": "m-hi",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "K",
             "owner": "owner@example.com", "name": "Hi",
             "connection_id": "hi", "active": True},
            {"provider": "p1", "model": "m-lo",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "K",
             "owner": "owner@example.com", "name": "Lo",
             "connection_id": "lo", "active": True},
            {"provider": "p1", "model": "m-dead",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "K",
             "owner": "owner@example.com", "name": "Dead",
             "connection_id": "dead", "active": True},
            {"provider": "p1", "model": "m-na",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "K",
             "owner": "owner@example.com", "name": "Na",
             "connection_id": "na", "active": True},
        ]
        self.state["routes"] = routes
        self.state["aa_scores"] = {"m-hi": 90.0, "m-lo": 10.0,
                                    "m-dead": 99.0}
        self.state["aa_stale"] = stale
        self.state["probe"] = {"hi": "ok", "lo": "ok",
                                 "dead": "down", "na": "ok"}
        self.state["matrix_cache"] = None

    def mod_headers(self, html):
        import re
        return re.findall(
            r'<th class="mod" data-p="([^"]*)" data-c="([^"]*)" '
            r'data-anyok="([01])"', html)

    def test_open_columns_aa_desc_unscored_last(self):
        self.open_state()
        code, raw, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        heads = self.mod_headers(raw.decode())
        self.assertEqual([c for _, c, _ in heads],
                         ["m-dead", "m-hi", "m-lo", "m-na"])

    def test_only_ok_columns_flagged_visible(self):
        self.open_state()
        code, raw, _ = self.call("GET", "/")
        flags = {c: v for _, c, v in self.mod_headers(raw.decode())}
        self.assertEqual(flags, {"m-dead": "0", "m-hi": "1",
                                 "m-lo": "1", "m-na": "1"})

    def test_matrix_json_keeps_all_columns_insertion_order(self):
        self.open_state()
        code, raw, _ = self.call("GET", "/api/v1/matrix")
        ids = [p["id"] for p in json.loads(raw)["providers"]]
        self.assertEqual(ids, ["m-hi", "m-lo", "m-dead", "m-na"])

    def test_stale_badge_tracks_aa_stale(self):
        self.open_state(stale=False)
        _, fresh, _ = self.call("GET", "/")
        self.assertIn('id="aastale" style="display:none"',
                      fresh.decode())
        self.open_state(stale=True)
        _, stale, _ = self.call("GET", "/")
        self.assertIn('id="aastale">', stale.decode())

    def test_legend_names_ok_only_view(self):
        self.open_state()
        _, raw, _ = self.call("GET", "/")
        self.assertIn("shows only ok models", raw.decode())


class InventoryWiringTest(RouteCase):
    def test_matrix_view_calls_enumerate_with_refresh(self):
        seen = {}

        def fake(routes, refresh=False):
            seen["n"] = len(routes)
            seen["refresh"] = refresh
            return {}
        server.enumerate_inventory = fake
        self.state["matrix_cache"] = None
        server.matrix_view(self.state, refresh=True)
        self.assertGreaterEqual(seen["n"], 1)
        self.assertTrue(seen["refresh"])


class ModelColumnsPageTest(RouteCase):
    """Page against the frozen model-column doc shape."""
    DOC = {
        "emails": ["a@b.cz"],
        "rows": [{"email": "a@b.cz", "cells": {
            "claude-opus": [{"connection_id": "c1", "name": "Opus",
                               "model": "claude-opus", "state": "ok",
                               "l1": "ok", "l2": "not-run",
                               "divergent": False, "checked_at": ""}]}}],
        "providers": [
            {"id": "claude-opus", "provider": "anthropic",
             "model": "claude-opus", "probed": True},
            {"id": "muse-x", "provider": "muse",
             "model": "muse-x", "probed": False}],
        "diagnostics": {"unassigned": [], "skippedInactive": [],
                         "divergent": []},
    }

    def render(self):
        orig = server.matrix_view
        server.matrix_view = lambda state, refresh=False: self.DOC
        try:
            return self.call("GET", "/")
        finally:
            server.matrix_view = orig

    def test_model_headers_with_provider_sub(self):
        code, body, _ = self.render()
        self.assertEqual(code, 200)
        self.assertIn(b'th class="prov" data-p="anthropic"', body)
        self.assertIn(b'th class="mod" data-p="muse" data-c="muse-x"',
                        body)
        self.assertIn(b"claude-opus", body)

    def test_provider_summary_and_toggle(self):
        _, body, _ = self.render()
        self.assertIn(b'td class="provsum" data-p="anthropic"', body)
        self.assertIn(b"EXP=new Set", body)
        self.assertIn(b"closest('th.prov')", body)
        self.assertEqual(server._worst_state(["ok", "suspect"]),
                         "suspect")
        self.assertEqual(server._worst_state(["unknown", "ok"]),
                         "unknown")
        self.assertEqual(server._worst_state([]), "unknown")
        self.assertEqual(server._worst_state(["down", "suspect", "ok"]),
                         "down")

    def test_unprobed_column_gray(self):
        _, body, _ = self.render()
        self.assertIn(b'class="mod unprobed"', body)
        self.assertIn(b'class="provsum unprobed"', body)

    def test_legend_colors_and_reload_hint(self):
        _, body, _ = self.render()
        for needle in (b"green ok", b"st-ok", b"st-unknown",
                       b"new models available", b"setInterval(poll,30000)",
                       b"data-cols="):
            self.assertIn(needle, body)



class TupleMatrixTest(RouteCase):
    """Per-key zen matrix: tuple list on top, per-key sections with
    validity verdicts; matrix JSON shape frozen (no new fields)."""

    T1 = "2026-09-19T10:00:00+00:00"
    T2 = "2026-09-19T11:00:00+00:00"

    def zen_state(self):
        routes = [
            {"provider": "opencode-zen", "model": "m1",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "ZEN_K1",
             "owner": "a@example.com", "name": "M1 one",
             "connection_id": "zen/m1-k1", "active": True},
            {"provider": "opencode-zen", "model": "m2",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "ZEN_K1",
             "owner": "a@example.com", "name": "M2 one",
             "connection_id": "zen/m2-k1", "active": True},
            {"provider": "opencode-zen", "model": "m1",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "ZEN_K2",
             "owner": "b@example.com", "name": "M1 two",
             "connection_id": "zen/m1-k2", "active": True},
            {"provider": "opencode-zen", "model": "m-ok",
             "base_url": "https://x.example", "api_key": "k",
             "wire": "openai", "env_var": "ZEN_K2",
             "owner": "b@example.com", "name": "MOk two",
             "connection_id": "zen/ok-k2", "active": True},
        ]
        self.state["routes"] = routes
        self.state["aa_scores"] = {}
        server.enumerate_inventory = lambda routes, refresh=False: \
            {"opencode-zen": ["m1", "m2", "m-ok"]}
        self.state["probe"] = {"zen/m1-k1": "degraded",
                             "zen/m2-k1": "down",
                             "zen/m1-k2": "down",
                             "zen/ok-k2": "ok"}
        self.state["probe_detail"] = {
            "zen/m1-k1": {"provider": "opencode-zen", "model": "m1",
                          "state": "degraded",
                          "detail": {"l1": "suspect"},
                          "checked_at": self.T1},
            "zen/m2-k1": {"provider": "opencode-zen", "model": "m2",
                          "state": "down",
                          "detail": {"l1": "suspect"},
                          "checked_at": self.T1},
            "zen/m1-k2": {"provider": "opencode-zen", "model": "m1",
                          "state": "down",
                          "detail": {"l1": "suspect"},
                          "checked_at": self.T2},
            "zen/ok-k2": {"provider": "opencode-zen", "model": "m-ok",
                          "state": "ok",
                          "detail": {"l1": "ok"},
                          "checked_at": self.T2},
        }
        self.state["matrix_cache"] = None

    def tuple_conns(self, html):
        import re
        return re.findall(r'<li data-t="([^"]+)\|[^"]*">', html)

    def test_tuples_match_l2_pass_pairs(self):
        self.zen_state()
        code, raw, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        conns = self.tuple_conns(raw.decode())
        self.assertIn("zen/m1-k1", conns)
        self.assertIn("zen/ok-k2", conns)
        self.assertNotIn("zen/m2-k1", conns)
        self.assertNotIn("zen/m1-k2", conns)
        self.assertIn(self.T1, raw.decode())
        self.assertIn("quota-aware", raw.decode())

    def test_perkey_sections_with_verdicts(self):
        self.zen_state()
        _, raw, _ = self.call("GET", "/")
        html = raw.decode()
        self.assertIn('<h3 data-k="ZEN_K1">', html)
        self.assertIn('<h3 data-k="ZEN_K2">', html)
        self.assertIn("CLI serves 1/2", html)
        self.assertIn("direct HTTP ok", html)
        self.assertIn('id="perkey"', html)
        self.assertIn("var KEYMAP=", html)
        self.assertIn("rebuildTuples", html)
        self.assertIn("rebuildPerKey", html)

    def test_verdict_branches_unit(self):
        fail = {"state": "down", "l1": "suspect", "l2": "fail",
                "checked_at": self.T1}
        v = server._zen_verdict("ZEN_K9", [("a@example.com", fail)])
        self.assertIn("no working path", v)
        self.assertIn("masked by cluster wall", v)
        vq = server._zen_verdict(
            "OPENCODE_ZEN_API_KEY", [("a@example.com", dict(fail))])
        self.assertIn("quota spent", vq)

    def test_detail_endpoint_returns_stored_evidence(self):
        self.zen_state()
        self.state["probe_detail"] = {
            "zen/m2-k1": {
                "provider": "opencode-zen", "model": "m2",
                "state": "down",
                "detail": {"l1": "suspect",
                             "l2": "exec-fail: quota spent"},
                "checked_at": self.T1}}
        code, raw, _ = self.call(
            "GET", "/api/v1/detail?connection=zen/m2-k1")
        self.assertEqual(code, 200)
        doc = json.loads(raw)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["record"]["detail"]["l2"],
                         "exec-fail: quota spent")
        self.assertNotIn("api_key", json.dumps(doc))
        code, _, _ = self.call("GET", "/api/v1/detail?connection=nope")
        self.assertEqual(code, 404)

    def test_matrix_json_shape_frozen(self):
        self.zen_state()
        _, raw, _ = self.call("GET", "/api/v1/matrix")
        allowed = {"connection_id", "name", "model", "state", "l1",
                   "l2", "divergent", "checked_at", "aa_score"}
        doc = json.loads(raw)
        for row in doc["rows"]:
            for entries in row["cells"].values():
                for e in entries:
                    self.assertLessEqual(set(e.keys()), allowed)





class ProbePersistTest(unittest.TestCase):
    def blank(self):
        return {"probe_detail": {}, "probe": {}, "matrix_cache": "x"}

    def test_hydrate_empty_without_files(self):
        old = os.environ.get("PROBE_DB")
        os.environ["PROBE_DB"] = os.path.join(
            tempfile.mkdtemp(), "nope.db")
        try:
            # no probe-seed.json next to server in test checkout... if the
            # repo file exists it hydrates; either way it must not raise
            n = server.hydrate_probe_state(self.blank())
            self.assertIsInstance(n, int)
        finally:
            if old is None:
                del os.environ["PROBE_DB"]
            else:
                os.environ["PROBE_DB"] = old

    def test_sqlite_roundtrip_and_overlay(self):
        tmp = os.path.join(tempfile.mkdtemp(), "p.db")
        old = os.environ.get("PROBE_DB")
        os.environ["PROBE_DB"] = tmp
        try:
            server.probe_db_save("zen/x",
                                 {"state": "ok", "checked_at": "t"})
            self.assertEqual(server.probe_db_load()["zen/x"]["state"],
                             "ok")
            st = self.blank()
            n = server.hydrate_probe_state(st)
            self.assertGreaterEqual(n, 1)
            self.assertEqual(st["probe_detail"]["zen/x"]["state"], "ok")
            self.assertEqual(st["probe"]["zen/x"], "ok")
            self.assertIsNone(st["matrix_cache"])
        finally:
            if old is None:
                del os.environ["PROBE_DB"]
            else:
                os.environ["PROBE_DB"] = old

    def test_ingest_persists_when_db_set(self):
        tmp = os.path.join(tempfile.mkdtemp(), "p.db")
        old = os.environ.get("PROBE_DB")
        os.environ["PROBE_DB"] = tmp
        try:
            st = server.make_state("tok", {"routes": []})
            st["routes"] = [
                {"provider": "opencode-zen", "model": "big-pickle",
                 "connection_id": "zen/retired-1"}]
            ok, err = server.ingest_probe(st, {
                "provider": "opencode-zen", "model": "big-pickle",
                "state": "ok", "detail": {"l1": "heartbeat"},
                "connection_id": "zen/retired-1",
                "checked_at": "2026-09-20T15:23:20Z"})
            self.assertTrue(ok, err)
            self.assertEqual(
                server.probe_db_load()["zen/retired-1"]["state"], "ok")
        finally:
            if old is None:
                del os.environ["PROBE_DB"]
            else:
                os.environ["PROBE_DB"] = old



class KeyqueueLiveTest(unittest.TestCase):
    BAKED = {"generated_at": "2026-09-20T15:00:00Z", "keys": [
        {"name": "K1", "state": "dead", "zencli": {"ok": False},
         "opencode": None, "mismatch": False, "retry_hint_secs": None,
         "checked_at": "2026-09-20T14:00:00Z", "consecutive_dead": 2,
         "next_test": "2026-09-20T18:00:00Z"},
        {"name": "K2", "state": "pending", "zencli": None,
         "opencode": None, "mismatch": False, "retry_hint_secs": None,
         "checked_at": None, "consecutive_dead": 0, "next_test": None}]}

    def rec(self, key, state, ts, mismatch=False):
        return {"provider": "opencode-zen", "model": "big-pickle",
                "state": state,
                "detail": {"l1": "heartbeat", "l2": "not-run",
                           "source": "keyround", "key_name": key,
                           "mismatch": mismatch,
                           "zencli": {"ok": state == "ok"},
                           "opencode": None},
                "checked_at": ts}

    def test_live_newer_wins_and_resets_streak(self):
        out = server.overlay_keyqueue_live(
            self.BAKED, {"zen/1": self.rec("K1", "ok",
                                           "2026-09-20T16:00:00Z")})
        k1 = [k for k in out["keys"] if k["name"] == "K1"][0]
        self.assertEqual(k1["state"], "ok")
        self.assertEqual(k1["consecutive_dead"], 0)
        self.assertEqual(k1["next_test"], "2026-09-20T17:00:00Z")
        self.assertTrue(k1["zencli"]["ok"])

    def test_live_down_extends_streak(self):
        out = server.overlay_keyqueue_live(
            self.BAKED, {"zen/1": self.rec("K1", "down",
                                           "2026-09-20T16:30:00Z")})
        k1 = [k for k in out["keys"] if k["name"] == "K1"][0]
        self.assertEqual(k1["state"], "dead")
        self.assertEqual(k1["consecutive_dead"], 3)
        self.assertEqual(k1["next_test"], "2026-09-21T00:30:00Z")

    def test_stale_live_and_non_keyround_ignored(self):
        out = server.overlay_keyqueue_live(self.BAKED, {
            "zen/1": self.rec("K1", "ok", "2026-09-20T13:00:00Z"),
            "zen/9": {"provider": "x", "model": "y", "state": "ok",
                      "detail": {"l1": "ok"}, "checked_at": "t"}})
        k1 = [k for k in out["keys"] if k["name"] == "K1"][0]
        self.assertEqual(k1["state"], "dead")  # baked stands
        self.assertEqual(len(out["keys"]), 2)  # no phantom keys

    def test_mismatch_visible_in_overlay(self):
        out = server.overlay_keyqueue_live(
            self.BAKED, {"zen/2": self.rec("K2", "down",
                                           "2026-09-20T16:00:00Z",
                                           mismatch=True)})
        k2 = [k for k in out["keys"] if k["name"] == "K2"][0]
        self.assertTrue(k2["mismatch"])
        self.assertEqual(k2["state"], "dead")


class FindRouteHealthTest(unittest.TestCase):
    def state(self, cids, probe):
        st = server.make_state("tok", {"routes": [
            {"provider": "p", "model": "m", "connection_id": c}
            for c in cids]})
        st["probe"] = dict(probe)
        return st

    def test_dead_first_seed_still_resolves_proven(self):
        st = self.state(["zen/dead", "zen/proven"],
                        {"zen/dead": "down", "zen/proven": "ok"})
        self.assertEqual(server.find_route(st, "m")["connection_id"],
                         "zen/proven")

    def test_unknown_beats_down(self):
        st = self.state(["zen/dead", "zen/new"],
                        {"zen/dead": "down"})
        self.assertEqual(server.find_route(st, "m")["connection_id"],
                         "zen/new")

    def test_seed_order_tiebreak(self):
        st = self.state(["zen/a", "zen/b"], {})
        self.assertEqual(server.find_route(st, "m")["connection_id"],
                         "zen/a")

    def test_no_match_none(self):
        st = self.state(["zen/a"], {})
        self.assertIsNone(server.find_route(st, "other"))



class StreakTest(unittest.TestCase):
    def state(self):
        st = server.make_state("tok", {"routes": [
            {"provider": "opencode-zen", "model": "big-pickle",
             "connection_id": "zen/pool-1"}]})
        return st

    def post(self, st, state, ts):
        ok, err = server.ingest_probe(st, {
            "provider": "opencode-zen", "model": "big-pickle",
            "state": state,
            "detail": {"l1": "heartbeat", "l2": "not-run",
                       "source": "keyround", "key_name": "K1"},
            "connection_id": "zen/pool-1", "checked_at": ts})
        self.assertTrue(ok, err)

    def test_streak_accumulates_across_ingests(self):
        st = self.state()
        self.post(st, "down", "2026-09-20T01:00:00Z")
        self.post(st, "down", "2026-09-20T04:00:00Z")
        self.post(st, "down", "2026-09-20T09:00:00Z")
        det = st["probe_detail"]["zen/pool-1"]["detail"]
        self.assertEqual(det["dead_streak"], 3)

    def test_recovery_resets_streak(self):
        st = self.state()
        self.post(st, "down", "2026-09-20T01:00:00Z")
        self.post(st, "ok", "2026-09-20T02:00:00Z")
        det = st["probe_detail"]["zen/pool-1"]["detail"]
        self.assertEqual(det["dead_streak"], 0)

    def test_streak_survives_db_roundtrip(self):
        import tempfile
        tmp = os.path.join(tempfile.mkdtemp(), "p.db")
        old = os.environ.get("PROBE_DB")
        os.environ["PROBE_DB"] = tmp
        try:
            st = self.state()
            self.post(st, "down", "2026-09-20T01:00:00Z")
            self.post(st, "down", "2026-09-20T04:00:00Z")
            loaded = server.probe_db_load()
            self.assertEqual(
                loaded["zen/pool-1"]["detail"]["dead_streak"], 2)
            st2 = self.state()
            st2["probe_detail"].update(loaded)
            self.post(st2, "down", "2026-09-20T09:00:00Z")
            self.assertEqual(
                st2["probe_detail"]["zen/pool-1"]["detail"][
                    "dead_streak"], 3)
        finally:
            if old is None:
                del os.environ["PROBE_DB"]
            else:
                os.environ["PROBE_DB"] = old

    def test_overlay_prefers_live_streak(self):
        baked = {"generated_at": "x", "keys": [
            {"name": "K1", "state": "dead", "zencli": None,
             "opencode": None, "mismatch": False,
             "retry_hint_secs": None, "checked_at": "2026-09-20T01:00:00Z",
             "consecutive_dead": 1, "next_test": "2026-09-20T03:00:00Z"}]}
        rec = {"provider": "opencode-zen", "model": "big-pickle",
               "state": "down",
               "detail": {"source": "keyround", "key_name": "K1",
                          "dead_streak": 5},
               "checked_at": "2026-09-20T09:00:00Z"}
        out = server.overlay_keyqueue_live(baked, {"zen/pool-1": rec})
        k1 = [k for k in out["keys"] if k["name"] == "K1"][0]
        self.assertEqual(k1["consecutive_dead"], 5)
        # 2^5 backoff capped: 09:00 + 24h
        self.assertEqual(k1["next_test"], "2026-09-21T09:00:00Z")


if __name__ == "__main__":
    unittest.main()
