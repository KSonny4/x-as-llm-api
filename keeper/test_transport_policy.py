"""Exact transport policy, upstream limits and conservative v1 migration."""
import json

from availability import Availability, Model, Result
from store import Store
from sweeps import Sweeps
from test_availability import setup, seed, free, succeed
from test_zencli_bridge import fixture
from zencli_bridge import BRIDGE_BASE
from inference import HttpResponse


def test_direct_free_zen_is_visible_but_never_probed_or_selected(tmp_path):
    s, clock, bridge, selector, calls = fixture(tmp_path)
    direct = next(c for c in s.connections() if c['protocol'] == 'openai')
    cli = next(c for c in s.connections() if c['protocol'] == 'zencli')
    assert direct['blocked_reason'] == 'cli_required'
    assert s.begin_check(direct['id']) is None
    assert selector.select(direct['model_id'])['error'] == 'no_working_connection'
    sid = selector.sweeps.schedule()
    assert selector.sweeps.progress(sid)['total'] == 2  # every key x CLI
    assert selector.sweeps.schedule(model_id=direct['model_id'])
    assert s.catalog()['models'] and len(s.connections()) == 4
    assert selector.select(cli['model_id'], export=False)['protocol'] == 'zencli'
    assert all(url.startswith('http://127.0.0.1:8099/') for _, url, _, _ in calls)
    assert s.accounts()['owners'][0]['state'] == 'working'


def test_upstream_limits_and_auth_are_exact_transport_not_manual_revocation(tmp_path):
    s, clock = setup(tmp_path, [seed()])
    models = [free('a'), free('b'), Model('p','a','https://other.test/v1','openai','free','pricing'),
              Model('p','a','https://example.test/v1','responses','free','pricing')]
    s.update_catalog('p', models)
    first = next(c for c in s.connections() if c['model_id'] == models[0].id)
    siblings = lambda: [c for c in s.connections() if c['base_url']==first['base_url'] and c['protocol']==first['protocol']]
    s.finish_check(s.begin_check(first['id']), Result('rate_limited',120))
    assert all(c['state']=='cooldown' for c in siblings())
    others = [c for c in s.connections() if c['id'] not in {x['id'] for x in siblings()}]
    for other in others: succeed(s,other)
    assert s.accounts()['keys'][0]['state']=='working'
    clock.advance(121)
    s.finish_check(s.begin_check(first['id']), Result('auth_invalid'))
    assert all(c['state']=='auth_invalid' for c in siblings())
    assert all(c['state']=='working' for c in s.connections() if c['id'] in {o['id'] for o in others})
    assert not s.accounts()['keys'][0]['revoked']
    with s.store.transaction() as db:
        db.execute('UPDATE av_credentials SET revoked=1')
    assert all(c['state']=='revoked' for c in s.connections())


def test_cli_429_survives_verifier_and_never_crosses_to_direct(tmp_path):
    s, clock, bridge, selector, calls = fixture(tmp_path)
    def limited(method,url,headers,payload):
        if url.endswith('/internal/catalog'): return HttpResponse(200,{},b'{}')
        return HttpResponse(429,{'Retry-After':'172800'},b'no diagnostics')
    bridge.transport = limited
    cli = next(c for c in s.connections() if c['protocol']=='zencli')
    result = bridge.verify(cli,'synthetic-selected',clock=clock)
    assert result == Result('rate_limited',172800)
    s.finish_check(s.begin_check(cli['id']),result)
    current = next(c for c in s.connections() if c['id']==cli['id'])
    assert current['state']=='cooldown' and current['retry_at']==clock()+172800
    assert selector.sweeps.claim(cli['id']) is None
    for status, state in [(401,'access_denied'),(403,'access_denied'),(500,'transient_error')]:
        bridge.transport=lambda *args: HttpResponse(200,{},b'{}') if args[1].endswith('/internal/catalog') else HttpResponse(status,{},b'{}')
        assert bridge.verify(cli,'synthetic-selected',clock=clock).state==state


def legacy_database(tmp_path, scopes, ambiguous=False):
    s, clock, bridge, selector, calls = fixture(tmp_path)
    rows = s.connections()
    kid = rows[0]['credential_id']
    with s.store.transaction() as db:
        # Construct genuine v1 shape; checks carry source transport but not retry duration.
        db.execute('DROP TABLE IF EXISTS av_transport_limits')
        db.execute('UPDATE av_schema SET version=1')
        db.execute('UPDATE av_credentials SET cooldown=?,revoked=1 WHERE id=?',(clock()+600,kid))
        for protocol in scopes:
            c=next(c for c in rows if c['credential_id']==kid and c['protocol']==protocol)
            db.execute("UPDATE av_connections SET state='rate_limited',checked_at=?,retry_at=? WHERE id=?",(clock(),clock()+300,c['id']))
            db.execute("INSERT INTO av_checks(connection_id,revision,key_revision,started_at,finished_at,state,applied) VALUES (?,0,0,?,?,'rate_limited',1)",(c['id'],clock()-1,clock()))
    s.store.close()
    return clock,kid


def test_v1_attributed_direct_limits_do_not_disqualify_cli_and_preserve_history(tmp_path):
    clock,kid = legacy_database(tmp_path,['openai'])
    s=Availability(Store(tmp_path/'availability.db'),clock)
    # Old revoked is ambiguous/manual: never auto-clear. Operator can review separately.
    assert next(k for k in s.accounts()['keys'] if k['id']==kid)['revoked']
    with s.store.transaction() as db: db.execute('UPDATE av_credentials SET revoked=0 WHERE id=?',(kid,))
    direct=next(c for c in s.connections() if c['credential_id']==kid and c['protocol']=='openai')
    cli=next(c for c in s.connections() if c['credential_id']==kid and c['protocol']=='zencli')
    assert direct['retry_at']==clock()+600 and s.history(direct['id'])[0]['state']=='rate_limited'
    assert cli['retry_at']==0 and s.begin_check(cli['id'])
    # Fresh evidence must come through bridge+queue+exact selection, not the
    # protected original receipt or a fabricated working observation.
    from zencli_bridge import ZenCLI
    from selection import Selector
    calls=[]
    def http(method,url,headers,payload):
        calls.append((url,headers,payload))
        return HttpResponse(200,{},b'{}' if url.endswith('/internal/catalog') else
                            json.dumps({'model':payload['model'],'choices':[{'message':{'content':'Hello'}}]}).encode())
    bridge=ZenCLI(s,'synthetic-internal',http)
    worker=Sweeps(s,provider_interval=0,key_interval=0,verifier=bridge.verify)
    selector=Selector(s,worker,lambda provider,ref:'synthetic-selected',verifier=bridge.verify,config_builder=bridge.config)
    with s.store.transaction() as db: db.execute('UPDATE av_credentials SET active=0 WHERE id<>?',(kid,))
    config=selector.select(cli['model_id'],export=False)
    assert config['connection_id']==cli['id']
    assert calls[-1][1]['X-Keeper-Provider-Key']=='synthetic-selected'
    assert calls[-1][2]['model']==cli['model']
    assert next(c for c in s.connections() if c['id']==cli['id'])['state']=='working'
    s.store.close()
    reopened=Availability(Store(tmp_path/'availability.db'),clock)
    assert next(c for c in reopened.connections() if c['id']==cli['id'])['retry_at']==0
    assert reopened.store.rows('SELECT version FROM av_schema')==[{'version':2}]


def test_v1_mixed_evidence_preserves_cli_limit_and_ambiguous_global(tmp_path):
    for name,scopes in [('mixed',['openai','zencli']),('unknown',[])]:
        directory=tmp_path/name; directory.mkdir()
        clock,kid=legacy_database(directory,scopes)
        s=Availability(Store(directory/'availability.db'),clock)
        with s.store.transaction() as db: db.execute('UPDATE av_credentials SET revoked=0')
        cli=next(c for c in s.connections() if c['credential_id']==kid and c['protocol']=='zencli')
        assert cli['retry_at']==clock()+600
        assert s.begin_check(cli['id']) is None
        assert cli['cooldown_scope']==('legacy_scope_unknown' if not scopes else 'exact_transport')


def test_sweep_pacing_and_running_claims_are_transport_scoped(tmp_path):
    s, clock=setup(tmp_path,[seed(),seed(key='KEY2')])
    models=[free('a'),free('b'),Model('p','a','https://example.test/v1','responses','free','pricing')]
    s.update_catalog('p',models)
    worker=Sweeps(s,provider_interval=30,key_interval=60)
    sid=worker.schedule()
    direct=next(c for c in s.connections() if c['model_id']==models[0].id)
    other=next(c for c in s.connections() if c['credential_id']==direct['credential_id'] and c['protocol']=='responses')
    sibling=next(c for c in s.connections() if c['credential_id']==direct['credential_id'] and c['model_id']==models[1].id)
    first=worker.claim(direct['id'])
    assert first
    assert worker.claim(sibling['id']) is None
    second=worker.claim(other['id'])
    assert second
    worker.complete(first,Result('rate_limited',120))
    worker.complete(second,Result('working'))
    assert worker.progress(sid)['done']==1
    s.store.close()
    s=Availability(Store(tmp_path/'availability.db'),clock)
    assert next(c for c in s.connections() if c['id']==other['id'])['state']=='working'
    assert next(c for c in s.connections() if c['id']==direct['id'])['state']=='cooldown'
    assert Sweeps(s).claim(sibling['id']) is None


def test_transport_auth_failure_fences_inflight_success_but_not_other_protocol(tmp_path):
    s,clock=setup(tmp_path,[seed()])
    models=[free('a'),free('b'),Model('p','a','https://example.test/v1','responses','free','pricing')]
    s.update_catalog('p',models)
    cells={c['model_id']:c for c in s.connections()}
    tickets=[s.begin_check(cells[m.id]['id']) for m in models]
    assert s.finish_check(tickets[0],Result('auth_invalid'))
    assert not s.finish_check(tickets[1],Result('working'))
    assert s.finish_check(tickets[2],Result('working'))
    assert s.accounts()['keys'][0]['state']=='working'


def test_transport_auth_failure_never_reappears_as_working_when_pricing_expires(tmp_path):
    s,clock=setup(tmp_path,[seed()])
    s.update_catalog('p',[free('a'),free('b')])
    a,b=s.connections()
    succeed(s,b)
    s.finish_check(s.begin_check(a['id']),Result('auth_invalid'))
    clock.advance(25*3600)
    assert all(c['state']=='auth_invalid' for c in s.connections())
    assert s.accounts()['keys'][0]['state']=='failed'


def test_schema_upgrade_rolls_back_atomically_and_can_retry(tmp_path,monkeypatch):
    import sqlite3
    import pytest
    clock,kid=legacy_database(tmp_path,['openai'])
    original=Store._migrate_transport_limits
    def interrupted(store):
        original(store)
        raise RuntimeError('synthetic migration interruption')
    with monkeypatch.context() as patch:
        patch.setattr(Store,'_migrate_transport_limits',interrupted)
        with pytest.raises(RuntimeError): Store(tmp_path/'availability.db')
    db=sqlite3.connect(tmp_path/'availability.db')
    assert db.execute('SELECT version FROM av_schema').fetchone()[0]==1
    assert db.execute('SELECT cooldown FROM av_credentials WHERE id=?',(kid,)).fetchone()[0]==clock()+600
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='av_transport_limits'").fetchone()
    db.close()
    s=Availability(Store(tmp_path/'availability.db'),clock)
    assert s.store.rows('SELECT version FROM av_schema')==[{'version':2}]
