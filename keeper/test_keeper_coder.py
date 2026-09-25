"""keeper-coder serving Cognee-style structured requests (Stage B hardening)."""
import json

import server
from credentials import RuntimeCredentials
from inference import HttpResponse
from selection import Selector
from sweeps import Sweeps
from test_api_v2 import call
from test_availability import setup, seed, free, succeed

HELLO = {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'extract'}]}
JSON_SCHEMA = {'type': 'json_schema', 'json_schema': {
    'name': 'KnowledgeGraph', 'strict': True,
    'schema': {'type': 'object', 'properties': {'nodes': {'type': 'array'}}}}}


def ok(model, content='{"nodes": []}'):
    return HttpResponse(200, {}, json.dumps({'model': model, 'choices': [
        {'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 3}}).encode())


def paid_state(tmp_path):
    """Free models a (AA 10) and b (AA 90) on two keys, plus escrowed paid pm."""
    routes = [seed(), seed(key='KEY2'),
              dict(seed('o', 'PAID', model='pm'), paid_eligibility=True)]
    service, clock = setup(tmp_path, routes)
    service.update_catalog('p', [free('a'), free('b')])
    selector = Selector(service, Sweeps(service, provider_interval=0, key_interval=0),
                        RuntimeCredentials(routes).resolve, lambda *a: ok(a[3]['model'], 'Hello'))
    for c in service.connections():
        if c['model'] in ('a', 'b', 'pm'):
            succeed(service, c)
    state = server.make_state('admin')
    state.update(availability=service, selector=selector, sweeps=selector.sweeps,
                 public_origin='https://keeper.example', service_token='service',
                 aa_scores={'a': 10, 'b': 90})
    return state


def serve(state, body):
    return call(state, 'POST', '/v1/chat/completions', body, {'Authorization': 'Bearer service'})


def test_json_schema_served_by_free_route_with_served_headers(tmp_path):
    state = paid_state(tmp_path); seen = []

    def http(method, url, headers, payload):
        seen.append(payload)
        return ok(payload['model'])
    state['inference_transport'] = http
    code, raw, headers = serve(state, {**HELLO, 'response_format': JSON_SCHEMA})
    assert code == 200 and json.loads(raw)['choices'][0]['message']['content'] == '{"nodes": []}'
    assert seen[0]['response_format'] == JSON_SCHEMA and seen[0]['model'] == 'b'
    h = dict(headers)
    assert h['X-Keeper-Model'] == 'b' and h['X-Keeper-Tier'] == 'free' and h['X-Keeper-Provider'] == 'p'


def test_free_failures_never_starve_the_paid_fallback(tmp_path):
    state = paid_state(tmp_path); seen = []

    def http(method, url, headers, payload):
        seen.append(payload['model'])
        return HttpResponse(503, {}, b'{}') if payload['model'] != 'pm' else ok('pm')
    state['inference_transport'] = http
    code, raw, headers = serve(state, {**HELLO, 'response_format': {'type': 'json_object'}})
    assert code == 200 and dict(headers)['X-Keeper-Tier'] == 'paid'
    assert seen[:3] == ['b', 'b', 'a'] and seen[-1] == 'pm'


def test_rejecting_model_is_skipped_for_the_next_model(tmp_path):
    state = paid_state(tmp_path); seen = []

    def http(method, url, headers, payload):
        seen.append(payload['model'])
        return HttpResponse(400, {}, b'{"error":"json_schema unsupported"}') if payload['model'] == 'b' else ok(payload['model'])
    state['inference_transport'] = http
    code, raw, headers = serve(state, {**HELLO, 'response_format': JSON_SCHEMA})
    assert code == 200 and seen == ['b', 'a'], 'one try per rejecting model, not per key'
    assert not any(c['excluded'] or c['state'] != 'working'
                   for c in state['availability'].connections() if c['model'] == 'b')


def test_request_every_free_model_rejects_is_not_sent_to_paid(tmp_path):
    state = paid_state(tmp_path); seen = []

    def http(method, url, headers, payload):
        seen.append(payload['model'])
        return HttpResponse(400, {}, b'{}')
    state['inference_transport'] = http
    code, raw, _ = serve(state, HELLO)
    assert code == 400 and json.loads(raw)['error']['code'] == 'upstream_rejected_request'
    assert 'pm' not in seen


def test_max_tokens_is_renamed_once_for_models_that_reject_it(tmp_path):
    state = paid_state(tmp_path); seen = []

    def http(method, url, headers, payload):
        seen.append(dict(payload))
        if 'max_tokens' in payload:
            return HttpResponse(400, {}, b'{"error":"use max_completion_tokens"}')
        return ok(payload['model'])
    state['inference_transport'] = http
    code, raw, _ = serve(state, {**HELLO, 'max_tokens': 256})
    assert code == 200 and len(seen) == 2
    assert seen[1]['max_completion_tokens'] == 256 and 'max_tokens' not in seen[1]
    assert seen[0]['model'] == seen[1]['model'], 'same connection, not a failover'


def test_litellm_bookkeeping_fields_are_dropped_not_rejected(tmp_path):
    state = paid_state(tmp_path); seen = []

    def http(method, url, headers, payload):
        seen.append(payload)
        return ok(payload['model'])
    state['inference_transport'] = http
    code, _, _ = serve(state, {**HELLO, 'metadata': {'run': 'x'}, 'store': True, 'service_tier': 'priority'})
    assert code == 200
    assert not {'metadata', 'store', 'service_tier'} & set(seen[0])


def test_no_route_503_tells_clients_when_to_retry(tmp_path):
    state = paid_state(tmp_path)
    state['inference_transport'] = lambda *a: HttpResponse(503, {}, b'{}')
    code, raw, headers = serve(state, HELLO)
    assert code == 503 and 15 <= int(dict(headers)['Retry-After']) <= 300
