"""Static private dashboard shell. No runtime data or secrets in HTML."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = {'/': ('dashboard.html', 'text/html; charset=utf-8'),
          '/assets/dashboard.js': ('dashboard.js', 'text/javascript; charset=utf-8'),
          '/assets/dashboard.css': ('dashboard.css', 'text/css; charset=utf-8')}
HEADERS = [('Cache-Control', 'no-store, private'), ('X-Content-Type-Options', 'nosniff'),
           ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
           ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]


def serve(path):
    filename, content_type = ASSETS[path]
    return 200, (ROOT / filename).read_bytes(), [('Content-Type', content_type)] + HEADERS
