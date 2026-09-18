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
        self.assertEqual(dict(headers).get("Cache-Control"), "max-age=600")

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
                       b"/api/v1/session/logout"):
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
        self.assertIn(b"claude-opus<br><small>anthropic</small>", body)
        self.assertIn(b"muse-x<br><small>muse</small>", body)

    def test_unprobed_column_gray(self):
        _, body, _ = self.render()
        self.assertIn(b'class="unprobed"', body)

    def test_legend_colors_and_reload_hint(self):
        _, body, _ = self.render()
        for needle in (b"green ok", b"st-ok", b"st-unknown",
                       b"new models available", b"setInterval(poll,30000)",
                       b"data-cols="):
            self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
