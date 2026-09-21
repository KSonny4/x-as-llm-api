"""Daily per-key verification budgets: checks spend the same quota they measure."""
from availability import (Availability, DAILY_CHECK_BUDGET, Model, Result,
                           utc_day_start)
from store import Store
from sweeps import Sweeps
from test_availability import Clock, setup, seed, free


def service_with_models(tmp_path, n, budget=2, state='working'):
    s, clock = setup(tmp_path, [seed()])
    s.update_catalog('p', [free(m) for m in ['m%d' % i for i in range(n)]])
    sweeps = Sweeps(s, provider_interval=0, key_interval=0, daily_budget=budget,
                    verifier=lambda job, secret, **k: Result(state))
    sweeps.schedule()
    return s, clock, sweeps


def drain(sweeps, secrets=None):
    resolved = secrets or (lambda provider, reference: 'synthetic')
    done = 0
    while sweeps.run_once(resolved):
        done += 1
        assert done < 50
    return done


def test_daily_budget_caps_background_claims(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 5, budget=2)
    assert drain(sweeps) == 2
    assert sweeps.claim() is None
    # Nothing assumed: unclaimed rows stay honestly unknown (seed model 'a'
    # is catalog_removed; m2..m4 are never-checked).
    assert sum(1 for c in s.connections() if c['observation_state'] == 'unknown') == 4
    # Just past UTC midnight the budget renews (staying inside catalog TTL).
    clock.advance(utc_day_start(clock()) + 86400 + 5 - clock())
    assert drain(sweeps) == 2
    assert sweeps.claim() is None


def test_oldest_first_rotation_not_fifo_starvation(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 3, budget=1)
    rows = {c['model']: c for c in s.connections()}
    first = sweeps.claim()
    assert first is not None
    sweeps.complete(first, Result('working'))
    # The next day must continue with a different, previously unchecked row.
    clock.advance(utc_day_start(clock()) + 86400 + 5 - clock())
    second = sweeps.claim()
    assert second is not None and second['id'] != first['id']
    assert second['checked_at'] is None


def test_ondemand_claim_bypasses_budget_but_counts(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 3, budget=1)
    assert drain(sweeps) == 1
    waiting = next(c for c in s.connections()
                   if c['observation_state'] == 'unknown' and not c['blocked_reason'])
    assert sweeps.claim(waiting['id']) is not None


def test_retry_due_outranks_never_checked(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 3, budget=10)
    first = next(c for c in s.connections() if c['model'] == 'm0')
    sweeps.complete(sweeps.claim(first['id']), Result('transient_error'))
    clock.advance(61)  # past retry backoff; fresh unknown rows exist too
    nxt = sweeps.claim()
    assert nxt is not None and nxt['id'] == first['id']


def test_full_coverage_completes_across_days_with_daily_refresh(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 3, budget=1)
    models = [free(m) for m in ['m%d' % i for i in range(3)]]
    for _ in range(3):
        assert drain(sweeps) == 1
        clock.advance(utc_day_start(clock()) + 86400 + 5 - clock())
        s.update_catalog('p', models)  # production daily refresh renews pricing
    assert all(c['observation_state'] == 'working'
               for c in s.connections() if c['model'].startswith('m'))


def test_budget_visible_per_key(tmp_path):
    s, clock, sweeps = service_with_models(tmp_path, 2, budget=2)
    assert drain(sweeps) == 2
    key = s.accounts()['keys'][0]
    assert key['checks_today'] == 2 and key['check_budget'] == DAILY_CHECK_BUDGET
