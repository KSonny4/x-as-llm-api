import json

import pytest

from inference import HttpResponse
from test_service_api import ready, service_call

BASE = {'model': 'keeper-coder', 'messages': [{'role': 'user', 'content': 'Hello'}]}


def test_static_model_metadata_does_not_buffer_normal_incremental_text():
    import service_api
    consumed = []
    def events():
        yield {'model': 'model:free', 'choices': [{'index': 0, 'delta': {'content': 'Hello'}, 'finish_reason': None}]}
        consumed.append('later')
        yield {'model': 'model:free', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
    chunks = service_api._validated_chunks(events(), {'protocol': 'openai', 'model': 'model:free', 'api_key': 'eyJ-synthetic-credential'})
    try:
        assert next(chunks)['choices'][0]['delta']['content'] == 'Hello'
        assert not consumed
    finally:
        chunks.close()


@pytest.mark.parametrize('kind', ['content', 'tool_arguments'])
def test_stream_cannot_disclose_a_credential_split_across_events(tmp_path, kind):
    state = ready(tmp_path)
    secrets = []
    def stream(config, payload):
        secret = config['api_key']; secrets.append(secret)
        half = len(secret) // 2
        for index, fragment in enumerate((secret[:half], secret[half:])):
            if kind == 'content':
                delta = {'content': fragment}
            else:
                arguments = ('{"value":"' if index == 0 else '') + fragment + ('"}' if index else '')
                delta = {'tool_calls': [{'index': 0, 'function': {'arguments': arguments}}]}
                if index == 0:
                    delta['tool_calls'][0].update(id='call_1', type='function')
                    delta['tool_calls'][0]['function']['name'] = 'consume'
            yield {'model': config['model'], 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
        yield {'model': config['model'], 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if kind == 'tool_arguments' else 'stop'}]}
    state['stream_transport'] = stream
    code, body, _ = service_call(state, '/v1/chat/completions', {**BASE, 'stream': True})
    raw = body if isinstance(body, bytes) else b''.join(body)
    emitted = ''
    for line in raw.decode().splitlines():
        if not line.startswith('data: {'): continue
        for choice in json.loads(line[6:]).get('choices', []):
            delta = choice.get('delta', {})
            emitted += delta.get('content', '')
            emitted += ''.join(c.get('function', {}).get('arguments', '') for c in delta.get('tool_calls', []))
    assert secrets and all(secret not in emitted for secret in secrets)
    assert code == 503 or b'upstream_failed' in raw


@pytest.mark.parametrize('change', [
    {'max_tokens': -1}, {'max_tokens': True}, {'max_completion_tokens': 0},
    {'temperature': 9}, {'temperature': 'warm'}, {'top_p': -0.1},
    {'n': 0}, {'frequency_penalty': float('nan')}, {'parallel_tool_calls': 'yes'},
    {'messages': [{'role': 'bogus', 'content': 'Hello'}]},
    {'messages': [{'role': 'tool', 'content': 'result'}]},
    {'tools': [{'type': 'function', 'function': {'name': 'run', 'parameters': []}}]},
    {'response_format': 'json'}, {'stream_options': {'include_usage': 'yes'}},
])
def test_invalid_request_is_rejected_before_selection_without_health_changes(tmp_path, change):
    state = ready(tmp_path); calls = []
    before = state['availability'].connections()
    before_checks = state['availability'].store.rows('SELECT * FROM av_checks')
    state['inference_transport'] = lambda *args: calls.append(args) or HttpResponse(400, {}, b'{}')
    code, _, _ = service_call(state, '/v1/chat/completions', {**BASE, **change})
    assert code == 400 and not calls
    assert state['availability'].connections() == before
    assert state['availability'].store.rows('SELECT * FROM av_checks') == before_checks
    assert not state['availability'].store.rows('SELECT * FROM av_feedback')


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('status', [400, 422])
def test_upstream_request_error_is_not_credential_failure(tmp_path, streaming, status):
    import service_api
    state = ready(tmp_path); calls = []
    before = {c['id']: (c['state'], c['checked_at'], c['excluded']) for c in state['availability'].connections()}
    def http(*args):
        calls.append(args)
        return HttpResponse(status, {}, b'{"error":"private diagnostic"}')
    def stream(config, payload):
        calls.append(payload)
        raise service_api.classify(status, {}, state['availability'].clock())
        yield
    state['inference_transport'] = http
    state['stream_transport'] = stream
    code, raw, _ = service_call(state, '/v1/chat/completions', {**BASE, 'stream': streaming})
    # Each model is tried once (a rejection moves to the next model, never
    # another key of the same model); all rejected -> honest 400.
    assert code == 400 and len(calls) == 2
    assert b'private diagnostic' not in raw
    assert {c['id']: (c['state'], c['checked_at'], c['excluded']) for c in state['availability'].connections()} == before
    assert not state['availability'].store.rows('SELECT * FROM av_feedback')
    assert not state['availability'].store.rows('SELECT * FROM av_checks WHERE finished_at IS NULL')
