import concurrent.futures
import json

from availability import Availability, Model, Result, CATALOG_TTL
from store import Store
from sweeps import Sweeps
from test_availability import setup, seed, free, succeed


def test_seed_verified_eligibility_expires_and_unknown_never_queues(tmp_path):
    routes = [seed(), seed(key='ELIGIBLE', model='explicit')]
    routes[1]['free_eligibility'] = {'kind': 'zero_price', 'provenance': 'https://provider.test/pricing',
                                     'verified_at': 1_800_000_000}
    s, clock = setup(tmp_path, routes)
    rows = s.connections()
    assert sum(c['blocked_reason'] is None for c in rows) == 2
    worker = Sweeps(s)
    assert worker.progress(worker.schedule())['total'] == 2
    clock.advance(CATALOG_TTL)
    s.sync_seeds(routes)
    assert all(c['blocked_reason'] for c in s.connections())
    assert worker.progress(worker.schedule())['total'] == 0


def test_catalog_change_invalidates_inflight_even_when_returned_to_free(tmp_path):
    s, _ = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    cid = s.connections()[0]['id']
    old = s.begin_check(cid)
    s.update_catalog('p', [Model('p', 'a', 'https://example.test/v1', 'openai', 'paid', 'public')])
    s.update_catalog('p', [free('a')])
    assert not s.finish_check(old, Result('working'))


def test_multi_store_claim_atomic_and_feedback_secret_redaction(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    a = Sweeps(s)
    other = Availability(Store(tmp_path / 'availability.db'), clock=clock)
    b = Sweeps(other)
    a.schedule()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        claims = list(pool.map(lambda worker: worker.claim(), [a, b]))
    assert sum(bool(c) for c in claims) == 1
    c = next(c for c in claims if c)
    s.report_failure(c['id'], 'synthetic-secret-KEY1')
    assert 'synthetic-secret' not in json.dumps(s.feedback(c['id']))


def test_disabled_metadata_fences_inflight_and_rotation_after_revocation(tmp_path):
    first = seed(credential_ref='KEY1@bao:1')
    s, _ = setup(tmp_path, [first])
    s.update_catalog('p', [free('a')])
    cid = s.connections()[0]['id']
    ticket = s.begin_check(cid)
    first['active'] = False
    s.sync_seeds([first])
    assert not s.finish_check(ticket, Result('working'))
    first['active'] = True
    s.sync_seeds([first])
    s.finish_check(s.begin_check(cid), Result('auth_invalid'))
    second = seed(credential_ref='KEY1@bao:2')
    s.sync_seeds([second])
    c = next(c for c in s.connections() if c['reference'] == 'KEY1@bao:2')
    assert c['state'] == 'unknown' and s.begin_check(c['id'])


def test_recent_failed_connection_supersedes_success(tmp_path):
    s, _ = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    c = s.connections()[0]
    succeed(s, c)
    s.finish_check(s.begin_check(c['id']), Result('invalid_response'))
    assert s.connections()[0]['state'] == 'invalid_response'


def test_invalid_database_timestamps_never_count_as_fresh(tmp_path):
    s, _ = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    c = s.connections()[0]
    succeed(s, c)
    with s.store.transaction() as db:
        db.execute('UPDATE av_connections SET checked_at=? WHERE id=?', ('not-a-timestamp', c['id']))
    assert s.connections()[0]['state'] == 'unknown'
    with s.store.transaction() as db:
        db.execute('UPDATE av_models SET checked_at=?', ('invalid',))
    assert s.connections()[0]['blocked_reason'] == 'catalog_stale'
