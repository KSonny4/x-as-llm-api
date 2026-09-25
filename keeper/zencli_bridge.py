"""Private genuine-CLI transport, never a direct-provider credential export.

Only a fixed authenticated Unix-socket sidecar is reachable. Discovery supplies
fresh authoritative zero-price eligibility; each execution receives the exact
selected key/model. Sidecar has no default account or durable secret store.
"""
import json
import time
import http.client
import os
import socket

from availability import BRIDGE_BASE, CATALOG_TTL, Model, NoEvidence, Result, evidence_age
from inference import HttpResponse, connection_config, verify as direct_verify, request, retry_after


def bridge_models(models):
    return [Model(m.provider, m.model, BRIDGE_BASE, 'zencli', m.eligibility,
                  m.provenance, m.requires_free_tier, m.verified_at)
            for m in models if m.provider == 'opencode-zen' and m.eligibility == 'free'
            and m.protocol in ('openai','responses','anthropic','gemini')]


DEFAULT_SOCKET = '/alloc/data/keeper-zencli/http.sock'


class BridgeUnavailable(NoEvidence):
    """The CLI sidecar itself is unreachable/unready: not key or model evidence."""


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__('keeper-zencli', timeout=120)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.connect(self.socket_path)
        except Exception:
            self.sock.close()
            raise


def unix_request(method, url, headers, payload, *, socket_path=None):
    # The authority is a logical identity, never a DNS/TCP destination. There
    # is no HTTP redirect/proxy handling and no caller-supplied IPC destination.
    if url not in (BRIDGE_BASE + '/chat/completions', BRIDGE_BASE.removesuffix('/v1') + '/internal/catalog'):
        raise ValueError('fixed bridge endpoint required')
    socket_path = socket_path or os.environ.get('KEEPER_ZENCLI_SOCKET', DEFAULT_SOCKET)
    if not os.path.isabs(socket_path):
        raise ValueError('absolute bridge socket required')
    conn = UnixHTTPConnection(socket_path)
    try:
        conn.request(method, url.removeprefix('http://keeper-zencli'), body=json.dumps(payload).encode(), headers=headers)
        res = conn.getresponse()
        body = res.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('bridge response too large')
        return HttpResponse(res.status, dict(res.headers), body)
    finally:
        conn.close()


class ZenCLI:
    def __init__(self, service, internal_token, transport=unix_request):
        if not internal_token:
            raise ValueError('internal bridge token required')
        self.service = service
        self._token = internal_token
        self.transport = transport

    def sync(self):
        # Push per-model original pricing timestamps, not renewed TTLs. Repeating
        # on each CLI use also recovers a restarted sidecar's ephemeral allowlist.
        models = self.service.store.rows("SELECT model,checked_at FROM av_models WHERE provider='opencode-zen' AND protocol='zencli' AND present=1 AND eligibility='free'")
        doc = {'models': [{'model': m['model'], 'verified_at': m['checked_at']} for m in models
                          if 0 <= evidence_age(m['checked_at'], self.service.clock()) < CATALOG_TTL]}
        try:
            res = self.transport('POST', BRIDGE_BASE.removesuffix('/v1') + '/internal/catalog',
                                 {'Authorization': 'Bearer ' + self._token, 'Content-Type':'application/json'}, doc)
        except OSError as exc:
            raise BridgeUnavailable('bridge unreachable') from exc
        if res.status != 200:
            raise BridgeUnavailable('bridge catalog unavailable')

    def config(self, c, secret):
        if c['protocol'] != 'zencli':
            return connection_config(c, secret)
        if c['base_url'] != BRIDGE_BASE or c['provider'] != 'opencode-zen':
            raise ValueError('invalid bridge identity')
        return {'protocol':'zencli', 'base_url':BRIDGE_BASE, 'endpoint':BRIDGE_BASE+'/chat/completions',
                'model':c['model'], 'api_key':secret, 'exportable':False,
                'secret_values':[secret,self._token],
                'headers':{'Authorization':'Bearer '+self._token,'X-Keeper-Provider-Key':secret,
                           'Content-Type':'application/json'}}

    def infer(self, config, payload):
        self.sync()
        return self.transport('POST', config['endpoint'], config['headers'], payload)

    def verify(self, c, secret, transport=request, clock=None):
        if c['protocol'] != 'zencli':
            kwargs = {'clock': clock} if clock else {}
            return direct_verify(c, secret, transport, **kwargs)
        if not secret:
            return Result('unsupported')
        try:
            res = self.infer(self.config(c,secret), {'model':c['model'], 'messages':[{'role':'user','content':'Reply Hello.'}]})
            if res.status == 429:
                return Result('rate_limited', retry_after(res.headers, (clock or time.time)()))
            if res.status != 200:
                return Result('access_denied' if res.status in (401,402,403) else 'transient_error')
            doc = res.json()
            if doc.get('model') != c['model']:
                return Result('model_mismatch')
            text = doc['choices'][0]['message']['content']
            return Result('working' if isinstance(text,str) and text.strip() and secret not in text and self._token not in text else 'invalid_response')
        except BridgeUnavailable:
            raise
        except Exception:
            return Result('transient_error')
