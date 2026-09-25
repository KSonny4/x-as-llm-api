"""Suspect recovery and request-path failure handling (2026-09-24 muse 2/10).

One bridge blip excluded 8 of 10 keys; serving traffic had exhausted the
per-key verification budget and suspects sorted last, so they stayed suspect
for a day. These pin the repaired behaviour.
"""
import json

from availability import (REQUEST_FAILURE_LIMIT, Result, utc_day_start)
from inference import HttpResponse
from sweeps import Sweeps
from test_availability import setup, seed, free, succeed
from test_service_api import ready, service_call
from test_verification_budget import drain, service_with_models
from test_zencli_bridge import fixture as bridge_fixture
from zencli_bridge import BridgeUnavailable


def _one(tmp_path):
    s, clock = setup(tmp_path, [seed('p', 'ONE')])
    s.update_catalog('p', [free('m')])
    cid = next(c['id'] for c in s.connections() if c['model'] == 'm')
    return s, clock, cid


def test_serving_checks_do_not_spend_verification_budget(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 3, budget=2)
    cid = next(c['id'] for c in s.connections() if c['model'] == 'm0')
    for _ in range(10):
        s.finish_check(s.begin_check(cid, kind='serve'), Result('working'))
    assert s.accounts()['keys'][0]['checks_today'] == 0
    assert drain(sweeps) == 2


def test_single_transient_cools_down_without_exclusion(tmp_path):
    s, clock, cid = _one(tmp_path)
    succeed(s, next(c for c in s.connections() if c['id'] == cid))
    assert s.finish_request_failure(s.begin_check(cid, kind='serve'), Result('transient_error'))
    c = next(c for c in s.connections() if c['id'] == cid)
    assert c['state'] == 'cooldown' and not c['excluded'] and c['observation_state'] == 'working'
    clock.advance(61)
    c = next(c for c in s.connections() if c['id'] == cid)
    assert c['state'] == 'working', 'eligible again after the short cooldown'


def test_consecutive_transients_escalate_then_mark_failed(tmp_path):
    s, clock, cid = _one(tmp_path)
    succeed(s, next(c for c in s.connections() if c['id'] == cid))
    delays = []
    for _ in range(REQUEST_FAILURE_LIMIT):
        before = clock()
        s.finish_request_failure(s.begin_check(cid, kind='serve'), Result('transient_error'))
        c = next(c for c in s.connections() if c['id'] == cid)
        delays.append(c['retry_at'] - before)
        clock.advance(c['retry_at'] - clock() + 1)
    assert delays == sorted(delays) and delays[1] > delays[0]
    c = next(c for c in s.connections() if c['id'] == cid)
    assert c['observation_state'] == 'transient_error' and not c['excluded']
    # A success resets the streak.
    s.finish_check(s.begin_check(cid), Result('working'))
    assert next(c for c in s.connections() if c['id'] == cid)['fail_streak'] == 0


def test_key_evidence_still_excludes(tmp_path):
    s, clock, cid = _one(tmp_path)
    succeed(s, next(c for c in s.connections() if c['id'] == cid))
    s.finish_request_failure(s.begin_check(cid, kind='serve'), Result('access_denied'))
    c = next(c for c in s.connections() if c['id'] == cid)
    assert c['excluded'] and c['state'] == 'suspect'


def test_suspect_recovers_first_despite_exhausted_budget(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 4, budget=1)
    assert drain(sweeps) == 1  # budget spent on a routine row
    suspect = next(c for c in s.connections() if c['model'] == 'm3')
    s.report_failure(suspect['id'], 'client_failure')
    sweeps.schedule()
    job = sweeps.claim()
    assert job is not None and job['id'] == suspect['id'], 'suspect first, past budget'
    assert sweeps.complete(job, Result('working'))
    c = next(c for c in s.connections() if c['id'] == suspect['id'])
    assert c['state'] == 'working' and not c['excluded']
    assert sweeps.claim() is None, 'routine rows still respect the budget'


def test_scoped_manual_check_bypasses_budget_unscoped_does_not(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 4, budget=1)
    assert drain(sweeps) == 1
    sweeps.schedule()
    assert sweeps.claim() is None
    target = next(c for c in s.connections() if c['model'] == 'm2')
    sweeps.schedule('manual', model_id=target['model_id'])
    job = sweeps.claim()
    assert job is not None and job['id'] == target['id']


def test_daily_sweep_is_due_at_utc_midnight(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 1)
    sweeps.schedule('daily', force=True)
    assert sweeps.refresh_due()[0] is False
    clock.advance(utc_day_start(clock()) + 86400 + 1 - clock())
    assert sweeps.refresh_due()[0] is True


def test_client_disconnect_is_not_evidence(tmp_path):
    state = ready(tmp_path)

    def stream(config, payload):
        yield {'model': payload['model'], 'choices': [{'index': 0, 'delta': {'content': 'hi'}, 'finish_reason': None}]}
        yield {'model': payload['model'], 'choices': [{'index': 0, 'delta': {'content': ' there'}, 'finish_reason': 'stop'}]}
    state['stream_transport'] = stream
    before = {c['id']: (c['state'], c['checked_at']) for c in state['availability'].connections()}
    code, body, _ = service_call(state, '/v1/chat/completions',
                                 {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'x'}], 'stream': True})
    assert code == 200
    next(iter(body))
    body.close()  # client went away mid-stream
    after = {c['id']: (c['state'], c['checked_at']) for c in state['availability'].connections()}
    assert after == before


def test_bridge_down_defers_worker_check_without_evidence(tmp_path):
    s, clock, bridge, select, calls = bridge_fixture(tmp_path)

    def down(method, url, headers, payload):
        raise ConnectionRefusedError()
    bridge.transport = down
    worker = Sweeps(s, provider_interval=0, key_interval=0, lease_seconds=150, verifier=bridge.verify)
    worker.schedule()
    before = {c['id']: c['observation_state'] for c in s.connections()}
    assert worker.run_once(lambda p, r: 'synthetic-secret')
    assert {c['id']: c['observation_state'] for c in s.connections()} == before
    assert s.accounts()['keys'][0]['checks_today'] == 0


def test_bridge_down_is_not_key_evidence_on_serving_path(tmp_path):
    s, clock, bridge, select, calls = bridge_fixture(tmp_path)
    for c in s.connections():
        if c['protocol'] == 'zencli':
            succeed(s, c)
    state = {'availability': s, 'selector': select, 'zencli': bridge, 'aa_scores': {}}

    def down(method, url, headers, payload):
        raise BridgeUnavailable('down')
    bridge.infer = lambda config, payload: down(None, None, None, None)
    from service_api import chat
    code, raw, _ = chat(state, json.dumps({'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'x'}]}).encode())
    assert code == 503
    cli = [c for c in s.connections() if c['protocol'] == 'zencli']
    assert all(c['state'] == 'working' and not c['excluded'] and c['fail_streak'] == 0 for c in cli)


def _hold_slot(bridge):
    """Occupy the only CLI slot from another thread until released."""
    import threading
    entered, release = threading.Event(), threading.Event()
    original = bridge.transport

    def blocking(method, url, headers, payload):
        if url.endswith('/chat/completions'):
            entered.set()
            release.wait(5)
        return original(method, url, headers, payload)
    bridge.transport = blocking
    config = bridge.config(next(c for c in bridge.service.connections() if c['protocol'] == 'zencli'), 'synthetic-secret')
    worker = threading.Thread(target=bridge.infer, args=(config, {'model': 'a', 'messages': []}))
    worker.start()
    assert entered.wait(5)
    return release, worker


def test_busy_cli_slots_defer_verification_without_evidence(tmp_path):
    from zencli_bridge import BridgeBusy
    s, clock, bridge, select, calls = bridge_fixture(tmp_path)
    bridge.concurrency, bridge.queue_wait = 1, 0
    import threading
    bridge._slots = threading.BoundedSemaphore(1)
    release, worker = _hold_slot(bridge)
    try:
        cli = next(c for c in s.connections() if c['protocol'] == 'zencli')
        try:
            bridge.verify(cli, 'synthetic-secret')
            assert False, 'expected BridgeBusy'
        except BridgeBusy:
            pass
    finally:
        release.set(); worker.join(5)
    # The slot is returned: the next run proceeds.
    assert bridge.verify(cli, 'synthetic-secret').state == 'working'


def test_slot_released_when_cli_transport_fails(tmp_path):
    s, clock, bridge, select, calls = bridge_fixture(tmp_path)
    import threading
    bridge._slots, bridge.queue_wait = threading.BoundedSemaphore(1), 0

    def boom(method, url, headers, payload):
        if url.endswith('/chat/completions'):
            raise ConnectionResetError()
        return HttpResponse(200, {}, b'{"ok":true}')
    bridge.transport = boom
    cli = next(c for c in s.connections() if c['protocol'] == 'zencli')
    for _ in range(3):
        assert bridge.verify(cli, 'synthetic-secret').state == 'transient_error'


def test_busy_cli_fails_over_without_penalizing_keys(tmp_path):
    s, clock, bridge, select, calls = bridge_fixture(tmp_path)
    for c in s.connections():
        if c['protocol'] == 'zencli':
            succeed(s, c)
    import threading
    bridge._slots, bridge.queue_wait = threading.BoundedSemaphore(1), 0
    logs, ctx = [], {}
    state = {'availability': s, 'selector': select, 'zencli': bridge, 'aa_scores': {}}
    release, worker = _hold_slot(bridge)
    try:
        from service_api import chat
        ctx['log'] = logs.append
        code, raw, _ = chat(state, json.dumps({'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'x'}]}).encode(),
                            ctx=ctx)
    finally:
        release.set(); worker.join(5)
    assert code == 503
    cli = [c for c in s.connections() if c['protocol'] == 'zencli']
    assert all(c['state'] == 'working' and not c['excluded'] and c['fail_streak'] == 0 for c in cli)
    assert any('"event": "zencli_busy"' in line for line in logs)
    # A busy slot is not an attempt: the free budget stays whole for overflow.
    assert [r['attempts'] for r in s.store.rows('SELECT attempts FROM av_usage')] == [0]
