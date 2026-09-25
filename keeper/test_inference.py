import json
import pytest
from inference import verify, HttpResponse, connection_config


def conn(protocol='openai'):
    return {'model': 'exact', 'base_url': 'https://provider.test/v1', 'protocol': protocol}


@pytest.mark.parametrize('protocol,doc,path,auth', [
    ('openai', {'model': 'exact', 'choices': [{'message': {'content': 'Hi'}}]}, '/chat/completions', 'Authorization'),
    ('responses', {'model': 'exact', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Hi'}]}]}, '/responses', 'Authorization'),
    ('anthropic', {'model': 'exact', 'content': [{'type': 'text', 'text': 'Hi'}]}, '/messages', 'x-api-key'),
    ('gemini', {'candidates': [{'content': {'parts': [{'text': 'Hi'}]}}]}, '/models/exact:generateContent', 'x-goog-api-key'),
])
def test_real_inference_exact_transport(protocol, doc, path, auth):
    calls = []
    def http(*args):
        calls.append(args)
        return HttpResponse(200, {}, json.dumps(doc).encode())
    assert verify(conn(protocol), 'synthetic-secret', http).state == 'working'
    method, url, headers, payload = calls[0]
    assert method == 'POST' and url.endswith(path)
    assert 'synthetic-secret' in headers[auth]
    assert 'synthetic-secret' not in url
    config = connection_config(conn(protocol), 'synthetic-secret')
    assert config['endpoint'] == url and config['headers'] == headers
    assert 'max_tokens' in payload or 'max_output_tokens' in payload or 'generationConfig' in payload


@pytest.mark.parametrize('status,doc,expected', [
    (200, {'error': {'message': 'synthetic-secret'}}, 'invalid_response'),
    (200, {'choices': [{'message': {'content': '  '}}]}, 'invalid_response'),
    (200, {'model': 'substitute', 'choices': [{'message': {'content': 'Hi'}}]}, 'model_mismatch'),
    (401, {'error': {'code': 'invalid_api_key'}}, 'auth_invalid'),
    (401, {'error': {'message': 'unauthorized'}}, 'access_denied'),
    (403, {'error': {'code': 'model_forbidden'}}, 'access_denied'),
    (402, {}, 'access_denied'),
    (500, {}, 'transient_error'),
])
def test_errors_never_become_working_or_leak(status, doc, expected):
    result = verify(conn(), 'synthetic-secret', lambda *a: HttpResponse(status, {}, json.dumps(doc).encode()))
    assert result.state == expected
    assert 'synthetic-secret' not in repr(result)


def test_retry_after_seconds_and_http_date_and_malformed():
    for value in ('120', 'Sun, 13 Sep 2020 12:28:40 GMT'):
        result = verify(conn(), 'secret', lambda *a: HttpResponse(429, {'Retry-After': value}, b'{}'), clock=lambda: 1600000000)
        assert result.state == 'rate_limited' and result.retry_after == 120
    assert verify(conn(), 'secret', lambda *a: HttpResponse(200, {}, b'not json')).state == 'invalid_response'

@pytest.mark.parametrize('version,expected', [('exact', 'working'), ('substitute', 'model_mismatch')])
def test_gemini_model_version_identity(version, expected):
    doc = {'modelVersion': version, 'candidates': [{'content': {'parts': [{'text': 'Hi'}]}}]}
    assert verify(conn('gemini'), 'synthetic', lambda *a: HttpResponse(200, {}, json.dumps(doc).encode())).state == expected


def test_verify_retries_max_completion_tokens_when_max_tokens_rejected():
    # Newer OpenAI models (o-series, gpt-6) 400 legacy max_tokens; the
    # verifier retries once with max_completion_tokens instead of failing.
    calls = []
    def http(method, url, headers, payload):
        calls.append(payload)
        if 'max_tokens' in payload:
            return HttpResponse(400, {}, json.dumps({'error': {
                'message': "Unsupported parameter: 'max_tokens'",
                'code': 'unsupported_parameter'}}).encode())
        return HttpResponse(200, {}, json.dumps({
            'model': 'exact', 'choices': [{'message': {'content': 'Hello'}}]}).encode())
    assert verify(conn(), 'synthetic-secret', http).state == 'working'
    assert len(calls) == 2
    assert 'max_tokens' not in calls[1] and calls[1]['max_completion_tokens'] == 64
