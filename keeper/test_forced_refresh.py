"""Operator-forced discovery refresh: durable min-interval, worker fulfillment."""
import threading
import time

import pytest

from availability import Result
from sweeps import FORCED_REFRESH_MIN_INTERVAL, Sweeps
from test_availability import free, setup
from test_api_v2 import call, state_for


def test_forced_schedule_min_interval(tmp_path):
    s, clock = setup(tmp_path)
    sweeps = Sweeps(s, provider_interval=0, key_interval=0)
    first = sweeps.schedule('forced')
    assert first is not None
    with pytest.raises(ValueError):
        sweeps.schedule('forced')
    clock.advance(FORCED_REFRESH_MIN_INTERVAL + 1)
    assert sweeps.schedule('forced') is not None


def test_forced_refresh_fulfills_enqueues_and_resets_daily(tmp_path):
    s, clock = setup(tmp_path)
    s.update_catalog('p', [free('a')])
    sweeps = Sweeps(s, provider_interval=0, key_interval=0,
                    verifier=lambda job, secret, **k: Result('working'))
    sweeps.schedule()  # baseline jobs
    assert sweeps.run_once(lambda provider, reference: 'synthetic') is True
    # Recent daily: no refresh due.
    s.store.rows("INSERT INTO av_sweeps(kind,created_at) VALUES ('daily',?)", (clock(),))
    assert sweeps.refresh_due() == (False, False)
    sweeps.schedule('forced')
    assert sweeps.refresh_due() == (False, True)
    refreshed = []
    stop = threading.Event()
    def refresh():
        refreshed.append(True)
        s.update_catalog('p', [free('a'), free('b')])
    worker = threading.Thread(target=sweeps.run,
                              args=(stop, lambda provider, reference: 'synthetic', refresh))
    worker.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if refreshed and any(m['model'] == 'b' for m in s.catalog()['models']):
            jobs = s.store.rows(
                "SELECT j.* FROM av_jobs j JOIN av_connections c ON c.id=j.connection_id "
                "JOIN av_models m ON m.id=c.model_id WHERE m.model='b'")
            if jobs:
                break
        time.sleep(0.2)
    stop.set()
    worker.join(timeout=10)
    assert refreshed, 'worker never ran the forced refresh'
    assert jobs, 'new rows never received check jobs'
    assert sweeps.refresh_due() == (False, False)


def test_forced_endpoint_202_then_409(tmp_path):
    from api_v2 import MUTATIONS
    assert '/api/v2/discovery/refresh' in MUTATIONS
    state, calls = state_for(tmp_path)
    assert call(state, 'GET', '/api/v2/discovery/refresh')[0] == 404
    code, body, _ = call(state, 'POST', '/api/v2/discovery/refresh', {})
    assert code == 202
    assert call(state, 'POST', '/api/v2/discovery/refresh', {})[0] == 409
    assert call(state, 'POST', '/api/v2/discovery/refresh', {'x': 'y'})[0] == 422
    assert not calls
