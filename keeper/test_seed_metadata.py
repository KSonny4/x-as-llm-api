import json
import os
from pathlib import Path
import subprocess

from availability import Availability
from discovery import CatalogDiscovery
from credentials import RuntimeCredentials
from test_availability import setup, seed, free, succeed


def test_renderer_missing_owner_authoritative_status_generation_and_kilo(tmp_path):
    bao = tmp_path / 'bao'
    bao.write_text('''#!/usr/bin/env python3
import json,sys
key=sys.argv[-1].split('/')[-1]
print(json.dumps({'data': {'metadata': {'version': 7}, 'data': {
 'key': 'synthetic-secret-' + key, 'status': 'active' if 'RETIRED' in key else 'disabled',
 'account_id': 'synthetic-account'
}}}))
''')
    bao.chmod(0o700)
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'render-seeds.sh'
    run = subprocess.run(['bash', str(script)], env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH']}, capture_output=True, text=True)
    assert run.returncode == 0
    routes = json.loads(run.stdout)['routes']
    pool = next(r for r in routes if r['env_var'] == 'OPENCODE_ZEN_RETIRED_1')
    assert pool['owner'] == '' and pool['active'] is True
    assert pool['credential_ref'] == 'OPENCODE_ZEN_RETIRED_1@bao:7'
    assert all(not r['active'] for r in routes if r['bao_status'] == 'disabled')
    kilo = next(r for r in routes if r['provider'] == 'kilocode')
    assert kilo['api_key'].startswith('synthetic-secret-')
    assert kilo['base_url'] == 'https://api.kilo.ai/api/gateway' and kilo['wire'] == 'openai'
    assert next(r for r in routes if r['provider'] == 'cloudflare-ai')['account_id'] == 'synthetic-account'
    assert 'synthetic-secret' not in run.stderr


def test_generation_rotation_never_reuses_proof_and_resolver_matches(tmp_path):
    old = seed(credential_ref='KEY1@bao:1')
    new = seed(credential_ref='KEY1@bao:2'); new['api_key'] = 'synthetic-new'
    s, _ = setup(tmp_path, [old])
    s.update_catalog('p', [free('a')])
    succeed(s, s.connections()[0])
    s.sync_seeds([new])
    cells = s.connections()
    assert next(c for c in cells if c['reference'] == 'KEY1@bao:1')['state'] == 'disabled'
    fresh = next(c for c in cells if c['reference'] == 'KEY1@bao:2')
    assert fresh['state'] == 'unknown'
    runtime = RuntimeCredentials([new])
    assert runtime.resolve(fresh['provider'], fresh['reference']) == 'synthetic-new'
    assert runtime.resolve('p', 'KEY1@bao:1') is None
    assert 'synthetic-new' not in repr(runtime)
