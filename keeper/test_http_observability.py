#!/usr/bin/env python3
"""HTTP observability tests: request IDs, access records, principal
classification, error-code extraction, Prometheus HTTP series.
Hermetic: pure helpers only, synthetic credentials, tmp state."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server


ADMIN = "admin-secret-value"
SERVICE = "service-secret-value"


def state(service_token=SERVICE):
    return {"service_token": service_token, "sessions": {}}


class TestReqId(unittest.TestCase):
    def test_honors_sane_incoming(self):
        self.assertEqual(server.http_req_id({"X-Request-ID": "abc-123_X.y"}),
                         "abc-123_X.y")

    def test_mints_when_absent_or_junk(self):
        a = server.http_req_id({})
        b = server.http_req_id({"X-Request-ID": "!!"})
        self.assertEqual(len(a), 16)
        self.assertNotEqual(a, b)

    def test_traceparent(self):
        h = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        self.assertEqual(server.http_trace_id(h), "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(server.http_trace_id({}), "")
        self.assertEqual(server.http_trace_id({"traceparent": "junk"}), "")


class TestNormRoute(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(server.norm_http_route("/healthz"), "healthz")
        self.assertEqual(server.norm_http_route("/v1/chat/completions"), "inference")
        self.assertEqual(server.norm_http_route("/v1/models"), "inference")
        self.assertEqual(server.norm_http_route("/api/v2/credentials"), "api_v2")
        self.assertEqual(server.norm_http_route("/api/v1/matrix"), "api_v1")
        self.assertEqual(server.norm_http_route("/v1/route/keeper-coder"), "route_info")
        self.assertEqual(server.norm_http_route("/nope"), "other")


class TestErrorCode(unittest.TestCase):
    def test_keeper_envelope(self):
        body = json.dumps({"error": {"message": "x", "type": "keeper_error",
                                     "code": "inference_only_token"}}).encode()
        self.assertEqual(server.http_error_code(403, body), "inference_only_token")

    def test_skips(self):
        self.assertEqual(server.http_error_code(200, b"{}"), "")
        self.assertEqual(server.http_error_code(403, b"not json"), "")
        self.assertEqual(server.http_error_code(503, iter([])), "")


class TestClassify(unittest.TestCase):
    def test_service(self):
        p, fp = server.classify_caller(
            {"Authorization": "Bearer " + SERVICE}, (ADMIN, ""), SERVICE, state())
        self.assertEqual(p, "service")
        self.assertEqual(len(fp), 12)
        self.assertNotIn(SERVICE, fp)

    def test_admin(self):
        p, fp = server.classify_caller(
            {"Authorization": "Bearer " + ADMIN}, (ADMIN, ""), SERVICE, state())
        self.assertEqual(p, "admin")

    def test_none(self):
        p, fp = server.classify_caller({}, (ADMIN, ""), SERVICE, state())
        self.assertEqual((p, fp), ("none", ""))

    def test_unknown_bearer_fingerprinted_not_logged(self):
        p, fp = server.classify_caller(
            {"Authorization": "Bearer wrong-guess"}, (ADMIN, ""), SERVICE, state())
        self.assertEqual(p, "none")
        self.assertEqual(len(fp), 12)
        self.assertNotIn("wrong-guess", fp)


class TestAccessRecord(unittest.TestCase):
    def test_whitelist_no_secrets(self):
        rec = server.http_access_record(
            "2026-09-21T22:30:00.000+00:00", "req1", "", "POST",
            "/v1/chat/completions", 403, 12.7, "service",
            "a1b2c3d4e5f6", "inference_only_token", "python-httpx/0.28.1")
        line = json.dumps(rec, sort_keys=True)
        for secret in (ADMIN, SERVICE, "wrong-guess", "Bearer"):
            self.assertNotIn(secret, line)
        self.assertEqual(rec["status"], 403)
        self.assertEqual(rec["err"], "inference_only_token")
        self.assertEqual(rec["ms"], 12)


class TestHttpMetrics(unittest.TestCase):
    def test_observe_and_view(self):
        st = state()
        server.http_observe(st, "inference", 403, 10)
        server.http_observe(st, "inference", 200, 1500)
        server.http_observe(None, "inference", 200, 1)  # never raises
        view = server.metrics_view(st)
        self.assertIn('keeper_http_responses_total{route="inference",code="403"} 1', view)
        self.assertIn('keeper_http_responses_total{route="inference",code="200"} 1', view)
        self.assertIn('keeper_http_latency_ms_count{route="inference"} 2', view)
        self.assertIn('keeper_http_latency_ms_sum{route="inference"} 1510', view)

    def test_absent_when_no_traffic(self):
        self.assertNotIn("keeper_http_responses_total", server.metrics_view(state()))


class FakeSelf:
    """Minimal _serve harness: real routing + observe + log, no sockets."""
    def __init__(self, path, headers, token, token_next, state):
        self.path = path
        self.headers = headers
        self.token = token
        self.token_next = token_next
        self.state = state
        self.sent = None

    def _read_body(self):
        return b""

    def _send(self, code, body, headers):
        self.sent = (code, body, list(headers))


class TestServeWiring(unittest.TestCase):
    def test_serve_observes_logs_and_echoes_req(self):
        import io
        from contextlib import redirect_stderr
        st = state()
        fake = FakeSelf("/v1/models", {"Authorization": "Bearer " + SERVICE},
                        ADMIN, "", st)
        buf = io.StringIO()
        with redirect_stderr(buf):
            server.H._serve(fake, "GET")
        code, _, headers = fake.sent
        self.assertEqual(code, 200)
        self.assertIn((server.REQ_ID_HEADER, fake_req(buf)), headers)
        # counter recorded -> visible in /metrics view
        view = server.metrics_view(st)
        self.assertIn('keeper_http_responses_total{route="inference",code="200"} 1', view)
        # log line carries principal + no secrets
        line = buf.getvalue()
        self.assertIn('"principal": "service"', line)
        self.assertNotIn(SERVICE, line)


def fake_req(buf):
    import json as _j
    return _j.loads(buf.getvalue().strip().splitlines()[-1])["req"]


if __name__ == "__main__":
    unittest.main()


class TestDoubledPrefix(unittest.TestCase):
    def test_models_doubled_path(self):
        code, body, _ = server.route(
            "GET", "/v1/v1/models", {"Authorization": "Bearer " + SERVICE},
            (ADMIN, ""), state=state())
        self.assertEqual(code, 200)
        self.assertIn("keeper-coder", body.decode())

    def test_exact_double_root(self):
        code, _, _ = server.route(
            "GET", "/v1/v1", {"Authorization": "Bearer " + SERVICE},
            (ADMIN, ""), state=state())
        # Normalizes to "/" (dashboard) which the service principal may not
        # read -> scope 403, never a bypass into another principal's view.
        self.assertEqual(code, 403)

    def test_normal_paths_untouched(self):
        code, _, _ = server.route(
            "GET", "/v1/models", {"Authorization": "Bearer nope"},
            (ADMIN, ""), state=state())
        self.assertEqual(code, 401)
