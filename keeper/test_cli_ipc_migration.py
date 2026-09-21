"""UDS changes IPC identity, never imports old success or direct cooldowns."""
import time

import pytest

from availability import Availability, Model
from store import Store
from test_zencli_bridge import fixture


@pytest.mark.parametrize('protocol,state,delay,evidenced,carried', [
    ('zencli','rate_limited',120,True,True),
    ('zencli','rate_limited',-10,True,False),
    ('zencli','rate_limited',120,False,False),
    ('zencli','auth_invalid',0,True,True),
    ('openai','rate_limited',120,True,False),
    ('openai','auth_invalid',0,True,False),
])
def test_cli_ipc_policy_migration_is_evidenced_attributed_and_idempotent(tmp_path,protocol,state,delay,evidenced,carried):
    service,clock,bridge,selector,calls=fixture(tmp_path)
    clock.value=time.time()
    base='http://127.0.0.1:8099/v1' if protocol=='zencli' else 'https://example.test/v1'
    old=Model('opencode-zen','historical',base,protocol,'unknown','old')
    with service.store.transaction() as db:
        service._put_model(db,old)
        service._expand(db)
        db.execute('UPDATE av_models SET checked_at=?',(clock(),))
        key=db.execute('SELECT id FROM av_credentials ORDER BY reference LIMIT 1').fetchone()[0]
        cid=db.execute('SELECT id FROM av_connections WHERE credential_id=? AND model_id=?',(key,old.id)).fetchone()[0]
        db.execute('UPDATE av_connections SET state=?,checked_at=? WHERE id=?',(state,clock()-1,cid))
        db.execute('INSERT INTO av_transport_limits(credential_id,base_url,protocol,cooldown,auth_invalid) VALUES (?,?,?,?,?)',
                   (key,base,protocol,clock()+delay if state=='rate_limited' else 0,int(state=='auth_invalid')))
        if evidenced:
            db.execute('INSERT INTO av_checks(connection_id,revision,key_revision,started_at,finished_at,state,applied) VALUES (?,0,0,?,?,?,1)',(cid,clock()-2,clock()-1,state))
        db.execute('DROP TABLE IF EXISTS av_transport_inheritance')
        db.execute('UPDATE av_schema SET version=2')
    service.store.close()
    service=Availability(Store(tmp_path/'availability.db'),clock)
    cli=next(c for c in service.connections() if c['credential_id']==key and c['protocol']=='zencli' and c['model']=='a')
    assert cli['observation_state']=='unknown' and cli['checked_at'] is None
    assert bool(service.store.rows('SELECT * FROM av_transport_inheritance')) is carried
    if carried:
        assert cli['policy_source']=='inherited prior CLI endpoint'
        assert cli['inherited_cli_base_url']==base
        assert service.begin_check(cli['id']) is None
        if state=='rate_limited':
            assert cli['retry_at']==clock()+delay
            assert cli['cooldown_scope']=='inherited_prior_cli_endpoint'
        else:
            assert cli['blocked_reason']=='auth_invalid'
    else:
        assert cli['retry_at']==0 and service.begin_check(cli['id'])
    assert service.store.rows('SELECT state,checked_at FROM av_connections WHERE id=?',(cid,))[0]['state']==state
    policies=service.store.rows('SELECT * FROM av_transport_inheritance')
    service.store.close()
    reopened=Availability(Store(tmp_path/'availability.db'),clock)
    assert reopened.store.rows('SELECT * FROM av_transport_inheritance')==policies
    assert reopened.store.rows('SELECT version FROM av_schema')==[{'version':3}]
