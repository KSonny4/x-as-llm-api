"""Tempo tracing: env-gated no-op + OTLP payload shape + local stub push."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import tracing


class _StubHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _StubHandler.received.append(json.loads(self.rfile.read(length)))
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _stub_server():
    srv = HTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_unconfigured_is_noop(monkeypatch):
    monkeypatch.delenv("TEMPO_OTLP_USER", raising=False)
    monkeypatch.delenv("TEMPO_OTLP_TOKEN", raising=False)
    assert tracing.tempo_config() is None
    assert tracing.emit_request_span(
        "", "/v1/chat/completions", 200, 5, "service", "") is False


def test_explicit_endpoint_needs_no_credentials(monkeypatch):
    monkeypatch.delenv("TEMPO_OTLP_USER", raising=False)
    monkeypatch.delenv("TEMPO_OTLP_TOKEN", raising=False)
    monkeypatch.setenv("TEMPO_OTLP_ENDPOINT", "http://127.0.0.1:9/none")
    assert tracing.tempo_config()[0] == "http://127.0.0.1:9/none"


def test_health_and_metrics_routes_skipped(monkeypatch):
    monkeypatch.setenv("TEMPO_OTLP_USER", "u")
    monkeypatch.setenv("TEMPO_OTLP_TOKEN", "t")
    assert tracing.emit_request_span(
        "a" * 32, "/healthz", 200, 1, "none", "") is False
    assert tracing.emit_request_span(
        "a" * 32, "/metrics", 200, 1, "admin", "") is False


def test_span_push_shape(monkeypatch):
    _StubHandler.received.clear()
    srv = _stub_server()
    try:
        monkeypatch.setenv("TEMPO_OTLP_USER", "u")
        monkeypatch.setenv("TEMPO_OTLP_TOKEN", "t")
        monkeypatch.setenv("TEMPO_OTLP_ENDPOINT",
                           "http://127.0.0.1:%d/otlp/v1/traces" % srv.server_port)
        tid = "b" * 32
        assert tracing.emit_request_span(
            tid, "/v1/chat/completions", 200, 12,
            "service", "") is True
        deadline = __import__("time").monotonic() + 10
        while not _StubHandler.received and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
        assert _StubHandler.received, "span never arrived"
        span = _StubHandler.received[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert span["traceId"] == tid
        assert len(span["spanId"]) == 16
        attrs = {a["key"]: a["value"]["stringValue"]
                 for a in span["attributes"]}
        assert attrs["http.route"] == "/v1/chat/completions"
        assert attrs["http.status"] == "200"
    finally:
        srv.shutdown()
