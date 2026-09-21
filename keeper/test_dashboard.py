import json
from test_api_v2 import state_for, call
from test_availability import free, seed


def test_dashboard_shell_has_no_provider_data_and_strict_assets(tmp_path):
    state, calls = state_for(tmp_path)
    code, body, headers = call(state, 'GET', '/')
    assert code == 200 and b'Accounts' in body and b'Models' in body
    assert b'dashboard.js' in body and b'synthetic-secret' not in body and b'example.test' not in body
    assert "default-src 'none'" in dict(headers)['Content-Security-Policy']
    assert not calls
    code, js, _ = call(state, 'GET', '/assets/dashboard.js')
    assert code == 200 and b'textContent' in js
    assert b'innerHTML' not in js and b'localStorage' not in js and b'sessionStorage' not in js
    assert call(state, 'GET', '/assets/../server.py')[0] == 404


def test_catalog_all_models_malicious_labels_and_polling(tmp_path):
    state, calls = state_for(tmp_path)
    s = state['availability']
    s.update_catalog('p', [free('m'+str(i)) for i in range(26)] + [free('<script>alert(1)</script>')])
    for _ in range(3):
        code, body, _ = call(state, 'GET', '/api/v2/catalog')
        models = json.loads(body)['models']
        assert len(models) >= 27 and any(m['model'].startswith('<script>') for m in models)
    assert not calls


def test_unchecked_and_stale_models_are_not_failed(tmp_path):
    from test_availability import succeed
    state,_=state_for(tmp_path)
    s=state['availability']
    assert s.catalog()['models'][0]['state']=='unknown'
    c=s.connections()[0];succeed(s,c);s.clock.advance(30*3600)
    assert next(m for m in s.catalog()['models'] if m['id']==c['model_id'])['state']=='stale'
    code,raw,_=call(state,'GET','/')
    assert b'https://artificialanalysis.ai/' in raw


def review_snapshot(directory):
    """Synthetic domain-to-browser fixture; no provider or secret-source reads."""
    from availability import Availability, Result
    from store import Store
    from sweeps import Sweeps
    from api_v2 import catalog
    from test_transport_policy import legacy_database
    from zencli_bridge import bridge_models

    clock, kid = legacy_database(directory, ['openai'])
    service = Availability(Store(directory / 'availability.db'), clock)
    routes = [seed('opencode-zen', 'ONE'), seed('opencode-zen', 'TWO'),
              dict(seed('unsupported-provider', 'UNSUPPORTED_KEY', model=''), owner='', wire='oauth'),
              dict(seed('signin-provider', 'SIGNIN_KEY', model=''), owner=''),
              dict(seed('disabled-provider', 'DISABLED_KEY', model='', active=False), owner=''),
              dict(seed('revoked-provider', 'REVOKED_KEY', model=''), owner='')]
    routes[3]['api_key'] = ''
    service.sync_seeds(routes)
    with service.store.transaction() as db:
        # Fixture's legacy helper intentionally sets ambiguous revoked. Here
        # model a's synthetic key is operator-cleared solely to isolate D1.
        db.execute('UPDATE av_credentials SET revoked=0 WHERE id=?', (kid,))
        db.execute("UPDATE av_credentials SET revoked=1 WHERE reference='REVOKED_KEY'")
    other = free('unchecked-sibling', 'opencode-zen')
    service.update_catalog('opencode-zen', [other, *bridge_models([other])], complete=False)
    state = {'availability': service, 'sweeps': Sweeps(service), 'build': 'synthetic-dashboard-review'}
    before = catalog(state)
    cli = next(c for c in service.connections() if c['credential_id'] == kid and c['protocol'] == 'zencli' and c['model'] == 'a')
    assert cli['state'] == cli['observation_state'] == 'unknown'
    assert cli['checked_at'] is None and cli['retry_at'] == 0
    ticket = service.begin_check(cli['id'])
    assert ticket  # Direct rate history must not block a never-checked CLI.
    service.finish_check(ticket, Result('rate_limited', 120))
    after = catalog(state)
    # A separate snapshot exercises the attributed migration-policy display;
    # test_cli_ipc_migration independently verifies when this row may be created.
    with service.store.transaction() as db:
        db.execute('''INSERT INTO av_transport_inheritance
            (credential_id,base_url,protocol,source_base_url,cooldown)
            VALUES (?,?,'zencli','http://127.0.0.1:8099/v1',?)''',
            (kid, cli['base_url'], clock()+300))
    prior_cli = catalog(state)
    service.store.close()
    return {'before': before, 'after': after, 'prior_cli': prior_cli, 'key_id': kid}


def test_key_admission_explains_model_less_keys_without_changing_health(tmp_path):
    snapshots = review_snapshot(tmp_path)
    keys = {k['reference']: k for k in snapshots['before']['keys']}
    for reference, reason in [('UNSUPPORTED_KEY', 'unsupported'), ('SIGNIN_KEY', 'signin_required'),
                              ('DISABLED_KEY', 'disabled'), ('REVOKED_KEY', 'revoked')]:
        key = keys[reference]
        assert key['admission_reason'] == reason
        assert key['owner'] is None and key['connections'] == [] and key['total'] == 0
    assert keys['UNSUPPORTED_KEY']['state'] == keys['SIGNIN_KEY']['state'] == 'unknown'
    assert keys['ONE']['admission_reason'] is None
    assert next(o for o in snapshots['before']['owners'] if o['owner'] is None)['total_keys'] == 4


def test_direct_rate_history_and_converse_cli_limit_have_separate_observations(tmp_path):
    snapshots = review_snapshot(tmp_path)
    key_id = snapshots['key_id']
    before = next(k for k in snapshots['before']['keys'] if k['id'] == key_id)['connections']
    after = next(k for k in snapshots['after']['keys'] if k['id'] == key_id)['connections']
    direct = next(c for c in before if c['model'] == 'a' and c['protocol'] == 'openai')
    assert direct['observation_state'] == 'rate_limited' and direct['checked_at'] is not None
    assert all(c['observation_state'] == 'unknown' and c['checked_at'] is None and c['retry_at'] == 0
               for c in before if c['protocol'] == 'zencli')
    observed = next(c for c in after if c['model'] == 'a' and c['protocol'] == 'zencli')
    inherited = next(c for c in after if c['model'] == 'unchecked-sibling' and c['protocol'] == 'zencli')
    assert observed['state'] == inherited['state'] == 'cooldown'
    assert observed['observation_state'] == 'rate_limited' and observed['checked_at'] is not None
    assert inherited['observation_state'] == 'unknown' and inherited['checked_at'] is None
    assert inherited['cooldown_scope'] == 'exact_transport'
    assert next(c for c in after if c['id'] == direct['id']) == direct


if __name__ == '__main__':
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        print(json.dumps(review_snapshot(Path(directory))))
