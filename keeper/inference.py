"""Small direct inference adapters and a redacting, non-redirecting HTTP transport.

Only usable generated text is evidence. Neither listing, CLI results, reasoning
text alone nor an HTTP 200 containing an error is success. No response bodies or
exception messages leave verify(). connection_config() is SECRET-BEARING and
must only be used inside a dedicated authenticated no-store response.
"""
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import json
import math
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from availability import Result, safe_base

USER_AGENT = 'keeper-availability/2.0'


@dataclass
class HttpResponse:
    status: int
    headers: dict
    body: bytes = field(repr=False)

    def json(self):
        return json.loads(self.body)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, url, headers, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        res = opener.open(req, timeout=25)
    except urllib.error.HTTPError as exc:
        res = exc
    with res:
        body = res.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ValueError('provider response too large')
        return HttpResponse(res.code, dict(res.headers), body)


def connection_config(c, secret):
    base = safe_base(c['base_url'])
    if not base:
        raise ValueError('unsupported endpoint')
    protocol = c['protocol']
    headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT}
    if protocol in ('openai', 'responses'):
        headers['Authorization'] = 'Bearer ' + secret
        path = '/chat/completions' if protocol == 'openai' else '/responses'
    elif protocol == 'anthropic':
        headers.update({'x-api-key': secret, 'anthropic-version': '2023-06-01'})
        path = '/messages'
    elif protocol == 'gemini':
        headers['x-goog-api-key'] = secret
        path = '/models/' + quote(c['model'], safe='') + ':generateContent'
    else:
        raise ValueError('unsupported protocol')
    return {'base_url': base, 'endpoint': base + path, 'protocol': protocol,
            'model': c['model'], 'headers': headers, 'api_key': secret}


def retry_after(headers, now):
    value = next((v for k, v in headers.items() if k.lower() == 'retry-after'), '')
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - now
        except (ValueError, TypeError, OverflowError):
            seconds = 60
    return max(1, seconds) if math.isfinite(seconds) else 60


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def verify(c, secret, transport=request, clock=time.time):
    if not secret:
        return Result('unsupported')
    try:
        config = connection_config(c, secret)
    except (ValueError, KeyError):
        return Result('unsupported')
    protocol = c['protocol']
    prompt = 'Reply with the word Hello.'
    payload = {'model': c['model'], 'messages': [{'role': 'user', 'content': prompt}],
               'max_tokens': 64, 'stream': False}
    if protocol == 'responses':
        payload = {'model': c['model'], 'input': prompt, 'max_output_tokens': 64, 'stream': False}
    elif protocol == 'gemini':
        payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                   'generationConfig': {'maxOutputTokens': 64}}
    try:
        res = transport('POST', config['endpoint'], config['headers'], payload)
    except Exception:
        return Result('transient_error')
    try:
        doc = res.json()
    except (ValueError, UnicodeError):
        doc = None
    if res.status == 429:
        return Result('rate_limited', retry_after(res.headers, clock()))
    if res.status >= 500 or res.status in (408, 425):
        return Result('transient_error')
    if res.status in (401, 402, 403):
        error = doc.get('error', {}) if isinstance(doc, dict) else {}
        code = error.get('code') if isinstance(error, dict) else None
        # Generic 401/403 can mean wrong route/auth scheme or per-model policy.
        return Result('auth_invalid' if res.status == 401 and code in
                      ('invalid_api_key', 'key_revoked', 'api_key_invalid') else 'access_denied')
    if res.status != 200 or not isinstance(doc, dict) or 'error' in doc:
        return Result('invalid_response')
    if any(doc.get(field) and doc[field] != c['model']
           for field in ('model', 'modelVersion') if field == 'model' or protocol == 'gemini'):
        return Result('model_mismatch')
    try:
        if protocol == 'openai':
            text = doc['choices'][0]['message']['content']
            ok = _text(text)
        elif protocol == 'responses':
            ok = any(_text(part.get('text')) for item in doc.get('output', [])
                     if item.get('type') == 'message' for part in item.get('content', [])
                     if part.get('type') == 'output_text')
        elif protocol == 'anthropic':
            ok = any(part.get('type') == 'text' and _text(part.get('text')) for part in doc['content'])
        else:
            ok = any(not part.get('thought') and _text(part.get('text'))
                     for item in doc.get('candidates', [])
                     for part in item.get('content', {}).get('parts', []))
    except (KeyError, IndexError, TypeError, AttributeError):
        ok = False
    return Result('working' if ok else 'invalid_response')
