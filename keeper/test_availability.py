import json
import sqlite3

import pytest

from availability import Availability, Model, Result, STALE_AFTER
from store import Store


class Clock:
    def __init__(self):
        self.value = 1_800_000_000.0
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


def seed(provider='p', key='KEY1', model='a', **extra):
    return dict(provider=provider, env_var=key, model=model,
                base_url='https://example.test/v1', wire='openai',
                api_key='synthetic-secret-' + key, owner='a@example.test', **extra)


def setup(tmp_path, seeds=None):
    clock = Clock()
    store = Store(tmp_path / 'availability.db')
    service = Availability(store, clock=clock)
    service.sync_seeds(seeds or [seed(), seed(key='KEY2')])
    return service, clock


def free(model, provider='p'):
    return Model(provider, model, 'https://example.test/v1', 'openai',
                 eligibility='free', provenance='https://example.test/pricing')


def succeed(service, connection):
    ticket = service.begin_check(connection['id'])
    assert ticket
    return service.finish_check(ticket, Result('working'))


def test_exact_cartesian_identity_and_any_success(tmp_path):
    s, clock = setup(tmp_path, [seed(), seed(model='b'), seed(key='KEY2'),
                               seed(provider='other')])
    s.update_catalog('p', [free(x) for x in 'abc'])
    s.update_catalog('other', [free('a', 'other')])
    rows = s.connections()
    assert len(rows) == 7
    assert len(s.accounts()['keys']) == 3
    b = next(c for c in rows if c['model'] == 'b')
    succeed(s, b)
    assert all(c['state'] != 'working' for c in s.connections() if c['model'] == 'a')
    assert sum(k['state'] == 'working' for k in s.accounts()['keys']) == 1
    assert s.accounts()['owners'][0]['state'] == 'working'
    sibling = next(c for c in rows if c['credential_id'] == b['credential_id'] and c['model'] == 'c')
    s.finish_check(s.begin_check(sibling['id']), Result('access_denied'))
    assert s.accounts()['owners'][0]['state'] == 'working'
    clock.advance(STALE_AFTER)
    assert next(c for c in s.connections() if c['id'] == b['id'])['state'] == 'stale'


def test_restart_history_feedback_race_and_no_secrets(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    c = s.connections()[0]
    old = s.begin_check(c['id'])
    s.report_failure(c['id'], 'rate_limited')
    assert not s.finish_check(old, Result('working'))
    assert s.connections()[0]['state'] == 'suspect'
    assert s.history(c['id'])[-1]['applied'] == 0
    db = tmp_path / 'availability.db'
    s.store.close()
    restarted = Availability(Store(db), clock=clock)
    assert restarted.connections()[0]['state'] == 'suspect'
    assert len(restarted.feedback(c['id'])) == 1
    dump = '\n'.join(restarted.store.db.iterdump())
    assert 'synthetic-secret' not in dump
    assert 'synthetic-secret' not in json.dumps(restarted.accounts())


def test_disabled_missing_owner_future_failure_and_revocation(tmp_path):
    one = seed(); one['owner'] = ''
    s, clock = setup(tmp_path, [one, seed(key='OFF', active=False)])
    s.update_catalog('p', [free('a'), free('b')])
    assert any(k['owner'] is None for k in s.accounts()['keys'])
    assert any(c['state'] == 'disabled' for c in s.connections())
    c = next(c for c in s.connections() if c['state'] != 'disabled')
    succeed(s, c)
    clock.advance(-10)
    assert next(x for x in s.connections() if x['id'] == c['id'])['state'] == 'unknown'
    clock.advance(10)
    s.finish_check(s.begin_check(c['id']), Result('auth_invalid'))
    assert all(x['state'] == 'revoked' for x in s.connections() if x['credential_id'] == c['credential_id'])
    s.sync_seeds([one, seed(key='OFF', active=False)])
    assert next(x for x in s.connections() if x['id'] == c['id'])['state'] == 'revoked'


def test_schema_preserves_old_tables_and_errors_propagate(tmp_path):
    path = tmp_path / 'availability.db'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE probe (value TEXT)')
    db.execute("INSERT INTO probe VALUES ('legacy')")
    db.commit(); db.close()
    s, _ = setup(tmp_path)
    assert s.store.db.execute('SELECT value FROM probe').fetchone()[0] == 'legacy'
    s.store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        s.connections()


def test_later_started_check_supersedes_old_check(tmp_path):
    s, _ = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    cid = s.connections()[0]['id']
    old = s.begin_check(cid)
    new = s.begin_check(cid)
    assert s.finish_check(new, Result('access_denied'))
    assert not s.finish_check(old, Result('working'))
    assert s.connections()[0]['state'] == 'access_denied'


def test_catalog_local_snapshot_separate_provider_identity_and_discovery_status(tmp_path):
    s, _ = setup(tmp_path, [seed(), seed(provider='other')])
    s.update_catalog('p', [free('a')])
    s.update_catalog('other', [free('a', 'other')])
    succeed(s, next(c for c in s.connections() if c['provider'] == 'p'))
    catalog = s.catalog()
    assert len(catalog['models']) == 2
    assert next(m for m in catalog['models'] if m['provider'] == 'p')['working_keys'] == 1
    assert next(m for m in catalog['models'] if m['provider'] == 'other')['working_keys'] == 0
    assert catalog['discovery'] == []
    assert 'synthetic-secret' not in json.dumps(catalog)


def test_all_confirmed_failures_are_failed_not_unchecked(tmp_path):
    s, _ = setup(tmp_path, [seed()])
    s.update_catalog('p', [free('a')])
    cid = s.connections()[0]['id']
    s.finish_check(s.begin_check(cid), Result('access_denied'))
    assert s.accounts()['keys'][0]['state'] == 'failed'
    assert s.accounts()['owners'][0]['state'] == 'failed'
