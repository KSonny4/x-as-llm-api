#!/usr/bin/env python3
"""Redacting deployment smoke. Read-only by default; no provider values printed.

Optional SMOKE_CHECKS=1 queues complete coverage. SMOKE_MODEL_ID retrieves one
verified exact configuration in memory. SMOKE_INFERENCE=1 exercises the service
alias. SMOKE_FAKE_FEEDBACK=1 requires a loopback base and an exact model ID;
use only the hermetic fake-provider harness, never a real healthy connection.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

BASE = os.environ.get('BASE', 'http://127.0.0.1:' + os.environ.get('PORT', '8080')).rstrip('/')


def req(path, token='', method='GET', doc=None):
    headers = {'User-Agent':'keeper-smoke/2.0'}
    if token: headers['Authorization'] = 'Bearer ' + token
    if doc is not None: headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(BASE + path, headers=headers, method=method,
        data=json.dumps(doc).encode() if doc is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=90) as res:
            return res.status, res.read(), dict(res.headers)
    except urllib.error.HTTPError as exc:
        with exc: return exc.code, exc.read(), dict(exc.headers)
    except Exception:
        return 0, b'', {}


def main():
    failed = []
    def check(name, ok):
        print(('ok: ' if ok else 'FAIL: ') + name, flush=True)
        if not ok: failed.append(name)
    code, body, _ = req('/healthz')
    check('public health', code == 200 and body == b'ok')
    for path in ('/packs', '/api/v2/catalog', '/api/v2/credentials'):
        check('unauthenticated rejection', req(path)[0] == 401)
    token = os.environ.get('KEEPER_TOKEN', '')
    if not token:
        check('administrator token configured', False)
    else:
        code, body, headers = req('/api/v2/catalog', token)
        check('authenticated catalog', code == 200)
        check('catalog no-store', 'no-store' in headers.get('Cache-Control', ''))
        try:
            catalog = json.loads(body)
            check('catalog complete shape', all(k in catalog for k in ('models','keys','owners','sweep','aa','build')))
            check('worker healthy', not catalog.get('worker_error'))
        except Exception:
            check('catalog JSON', False)
        code, body, _ = req('/', token)
        check('private dashboard shell', code == 200 and b'dashboard.js' in body and b'Accounts' in body)
        if os.environ.get('SMOKE_CHECKS') == '1':
            check('paced check scheduling', req('/api/v2/checks',token,'POST',{})[0] == 202)
        model = os.environ.get('SMOKE_MODEL_ID')
        if model:
            code, raw, headers = req('/api/v2/credentials',token,'POST',{'model_id':model})
            check('verified credential retrieval', code == 200)
            check('credential no-store', 'no-store' in headers.get('Cache-Control', ''))
            if code == 200:
                config = json.loads(raw)
                check('exact credential identity', config.get('model_id') == model and bool(config.get('api_key')))
                if os.environ.get('SMOKE_FAKE_FEEDBACK') == '1':
                    # Explicit test-only marker supplied by the hermetic server,
                    # not merely loopback (production smoke also uses loopback).
                    fake = os.environ.get('SMOKE_FIXTURE') == 'synthetic-only'
                    if fake and urlsplit(BASE).hostname in ('127.0.0.1','localhost'):
                        status, raw, _ = req('/api/v2/feedback',token,'POST',{'connection_id':config['connection_id'],'reason':'client_failure'})
                        replacement = json.loads(raw)
                        check('fixture precise replacement', status == 200 and replacement.get('model_id') == model and replacement.get('connection_id') != config['connection_id'])
                    else:
                        check('fixture-only feedback guard', False)
                config.clear()
                raw = b''
    for env, want in [('KEEPER_TOKEN_NEXT',200),('KEEPER_TOKEN_OLD',401)]:
        if os.environ.get(env): check('administrator rotation boundary',req('/api/v2/catalog',os.environ[env])[0] == want)
    service = os.environ.get('KEEPER_SERVICE_TOKEN', '')
    if service:
        check('service model alias',req('/v1/models',service)[0] == 200)
        for path in ('/packs','/api/v2/catalog','/'):
            check('service isolation', req(path,service)[0] == 403)
        if os.environ.get('SMOKE_INFERENCE') == '1':
            code, body, _ = req('/v1/chat/completions',service,'POST',{'model':'keeper-coder','messages':[{'role':'user','content':'Reply Hello.'}]})
            try: usable = bool(json.loads(body)['choices'][0]['message']['content'])
            except Exception: usable = False
            check('service real inference',code == 200 and usable)
    check('invalid token rejection',req('/api/v2/catalog','wrong-bearer-smoke')[0] == 401)
    print('SMOKE RED' if failed else 'SMOKE GREEN',flush=True)
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
