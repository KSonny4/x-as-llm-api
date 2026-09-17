#!/usr/bin/env python3
"""Keeper v2 skeleton (L1). Stdlib only. KEEPER_TOKEN bearer on everything
except GET /healthz. Later lanes add packs/feedback/v1/translate/matrix here
behind the same auth discipline (additive, versioned in KEEPER_API.md)."""
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", "8080"))


def require_token(token):
    if not token:
        sys.stderr.write("FATAL: KEEPER_TOKEN unset — refusing to serve\n")
        raise SystemExit(1)
    return token


def route(method, path, headers, token):
    """Pure routing: (status, body_bytes, extra_headers). No sockets."""
    if method == "GET" and path == "/healthz":
        return 200, b"ok", [("Content-Type", "text/plain")]
    auth = ""
    for k, v in headers.items():
        if k.lower() == "authorization":
            auth = v
    if auth != "Bearer " + token:
        return 401, b"unauthorized", [("Content-Type", "text/plain")]
    return 404, b"not found", [("Content-Type", "text/plain")]


class H(BaseHTTPRequestHandler):
    server_version = "keeper/2-skeleton"
    token = ""

    def log_message(self, *a):
        sys.stderr.write("%s %s %s\n" % (self.log_date_time_string(),
                                         self.command, self.path))

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        code, body, headers = route("GET", self.path, dict(self.headers),
                                    self.token)
        self._send(code, body, headers)


def main():
    token = require_token(os.environ.get("KEEPER_TOKEN", ""))
    H.token = token
    print(f"keeper skeleton on 0.0.0.0:{PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
