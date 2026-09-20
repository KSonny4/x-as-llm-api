import json
from availability import Availability, Result
from credentials import RuntimeCredentials
from inference import HttpResponse
from selection import Selector
from store import Store
from sweeps import Sweeps
from test_availability import setup, free, succeed, seed


def fixture(tmp_path):
    routes = [seed(), seed(key='KEY2')]
    service, clock = setup(tmp_path, routes)
    service.update_catalog('p', [free('a'), free('b')])
    calls = []
    def http(method, url, headers, payload):
        calls.append((url, headers, payload))
        return HttpResponse(200, {}, json.dumps({'model': payload['model'], 'choices': [{'message': {'content': 'Hello'}}]}).encode())
    selector = Selector(service, Sweeps(service, provider_interval=0, key_interval=0), RuntimeCredentials(routes).resolve, http)
    return service, clock, selector, calls


def test_freshest_exact_selection_then_five_minute_revalidation(tmp_path):
    s, clock, selector, calls = fixture(tmp_path)
    cells = [c for c in s.connections() if c['model'] == 'a']
    succeed(s, cells[0]); clock.advance(2); succeed(s, cells[1])
    result = selector.select(cells[0]['model_id'])
    assert result['connection_id'] == cells[1]['id'] and not calls
    assert result['model'] == 'a' and result['protocol'] == 'openai'
    assert result['api_key'] == 'synthetic-secret-KEY2'
    clock.advance(301)
    assert selector.select(cells[0]['model_id'])['connection_id'] == cells[1]['id']
    assert len(calls) == 1


def test_feedback_excludes_precise_identity_and_replacement_verified(tmp_path):
    s, clock, selector, calls = fixture(tmp_path)
    a = [c for c in s.connections() if c['model'] == 'a']
    for cell in a: succeed(s, cell)
    result = selector.replace(a[0]['id'], 'access_denied')
    assert result['connection_id'] == a[1]['id'] and result['model'] == 'a'
    assert len(calls) == 1
    restarted = Availability(Store(tmp_path / 'availability.db'), clock)
    assert len(restarted.feedback(a[0]['id'])) == 1
    assert next(c for c in restarted.connections() if c['id'] == a[0]['id'])['excluded']
    assert all(not c['excluded'] for c in restarted.connections() if c['model'] == 'b')
    assert 'synthetic-secret' not in '\n'.join(s.store.db.iterdump())


def test_cooldown_exclusion_no_substitution_and_bounded_no_candidate(tmp_path):
    s, clock, selector, calls = fixture(tmp_path)
    a = [c for c in s.connections() if c['model'] == 'a']
    for cell in a: s.report_failure(cell['id'])
    assert selector.select(a[0]['model_id'])['error'] == 'no_working_connection'
    assert not calls
    b = next(c for c in s.connections() if c['model'] == 'b')
    s.finish_check(s.begin_check(b['id']), Result('rate_limited', 120))
    result = selector.select(b['model_id'])
    assert result['model'] == 'b' and result['connection_id'] != b['id']


def test_failed_probe_returns_no_credential_and_redacts(tmp_path):
    s, clock, selector, calls = fixture(tmp_path)
    selector.transport = lambda *a: HttpResponse(500, {}, b'synthetic-secret-KEY1')
    result = selector.select(s.connections()[0]['model_id'])
    assert result['error'] in ('verification_pending', 'no_working_connection')
    assert 'api_key' not in result and 'synthetic' not in json.dumps(result)
