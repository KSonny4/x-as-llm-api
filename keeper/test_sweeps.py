from availability import Availability, Result
from store import Store
from sweeps import Sweeps
from test_availability import setup, free, seed


def test_complete_sweep_no_early_exit_overlap_pacing_and_daily(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('m' + str(i)) for i in range(25)])
    sweep = Sweeps(s, provider_interval=2, key_interval=3)
    first = sweep.schedule()
    second = sweep.schedule()
    assert sweep.progress(first)['total'] == 50
    assert len(s.store.rows('SELECT * FROM av_jobs')) == 50
    assert sweep.schedule('daily')
    assert sweep.schedule('daily') is None
    count = 0
    while sweep.progress(first)['pending']:
        job = sweep.claim()
        if job:
            sweep.complete(job, Result('working'))
            count += 1
            assert sweep.claim() is None
        clock.advance(3)
    assert count == 50
    assert sweep.progress(second)['done'] == 50


def test_rate_limit_other_key_continues_manual_cannot_bypass_and_bounded_retry(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('a'), free('b')])
    sweep = Sweeps(s, provider_interval=1, key_interval=1, max_attempts=2)
    sid = sweep.schedule()
    job = sweep.claim()
    sweep.complete(job, Result('rate_limited', 120))
    sweep.schedule()
    clock.advance(1)
    other = sweep.claim()
    assert other['credential_id'] != job['credential_id']
    sweep.complete(other, Result('working'))
    clock.advance(1)
    other2 = sweep.claim()
    assert other2['credential_id'] == other['credential_id']
    sweep.complete(other2, Result('working'))
    assert sweep.claim() is None
    clock.advance(120)
    retry = sweep.claim()
    sweep.complete(retry, Result('rate_limited', 120))
    assert s.store.rows('SELECT state FROM av_jobs WHERE id=?', (retry['job_id'],))[0]['state'] == 'done'
    assert sweep.progress(sid)['pending'] == 1


def test_restart_lease_recovery_and_old_result_fenced(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    worker = Sweeps(s, lease_seconds=30)
    sid = worker.schedule()
    old = worker.claim()
    new_service = Availability(Store(tmp_path / 'availability.db'), clock=clock)
    restarted = Sweeps(new_service, lease_seconds=30)
    # A second process must not steal an unexpired lease.
    assert restarted.claim() is None
    clock.advance(31)
    fresh = restarted.claim()
    assert fresh['job_id'] == old['job_id']
    assert not worker.complete(old, Result('working'))
    assert restarted.complete(fresh, Result('access_denied'))
    assert next(c for c in s.connections() if c['id'] == fresh['id'])['state'] == 'access_denied'


def test_feedback_during_job_schedules_fresh_verification(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    worker = Sweeps(s, provider_interval=1, key_interval=1)
    worker.schedule()
    job = worker.claim()
    s.report_failure(job['id'], 'access_denied')
    assert not worker.complete(job, Result('working'))
    clock.advance(2)
    fresh = worker.claim()
    assert fresh['id'] == job['id']
    assert worker.complete(fresh, Result('working'))
    assert next(c for c in s.connections() if c['id'] == job['id'])['state'] == 'working'


def test_revocation_blocks_sibling_jobs_but_malformed_is_not_key_wide(tmp_path):
    s, clock = setup(tmp_path, [seed()])
    s.update_catalog('p', [free('a'), free('b')])
    worker = Sweeps(s, provider_interval=1, key_interval=1)
    sid = worker.schedule()
    job = worker.claim()
    worker.complete(job, Result('invalid_response'))
    clock.advance(2)
    job = worker.claim()
    assert job
    worker.complete(job, Result('auth_invalid'))
    assert all(c['state'] == 'revoked' for c in s.connections())
    assert worker.progress(sid)['done'] == 2


def test_worker_fake_provider_end_to_end_no_paid_or_cli_evidence(tmp_path):
    import json
    from credentials import RuntimeCredentials
    from inference import HttpResponse
    from availability import Model
    routes = [seed('p', 'ONE'), seed('p', 'TWO'), seed('other', 'THREE')]
    s, clock = setup(tmp_path, routes)
    s.update_catalog('p', [free('a'), free('b'), Model('p', 'paid', 'https://example.test/v1', 'openai', 'paid', 'public')])
    s.update_catalog('other', [free('a', 'other')])
    worker = Sweeps(s, provider_interval=0, key_interval=0)
    sid = worker.schedule()
    calls = []
    def http(method, url, headers, payload):
        calls.append(payload['model'])
        return HttpResponse(200, {}, json.dumps({'model': payload['model'],
            'choices': [{'message': {'content': 'Hello'}}]}).encode())
    secrets = RuntimeCredentials(routes)
    while worker.run_once(secrets.resolve, http):
        pass
    assert len(calls) == 5 and 'paid' not in calls
    assert worker.progress(sid)['done'] == 5
    assert all(k['state'] == 'working' for k in s.accounts()['keys'])
    assert 'synthetic-secret' not in '\n'.join(s.store.db.iterdump())


def test_feedback_on_exhausted_lease_survives_restart_once(tmp_path):
    s, clock = setup(tmp_path, [seed()])
    s.update_catalog('p', [free('a')])
    worker = Sweeps(s, lease_seconds=30, max_attempts=1)
    worker.schedule()
    old = worker.claim()
    s.report_failure(old['id'])
    clock.advance(31)
    restarted = Sweeps(Availability(Store(tmp_path / 'availability.db'), clock), lease_seconds=30, max_attempts=1)
    fresh = restarted.claim()
    assert fresh and fresh['id'] == old['id']
    clock.advance(31)
    assert restarted.claim() is None  # no new feedback: bounded exhaustion
