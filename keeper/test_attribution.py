"""Caller + cost attribution: consumer tokens, usage rows, prices, metrics, logs, spans."""
import json

import pytest

import runtime
import server
import tracing
import usage_metrics
from discovery import parse_zen, price_pair, with_prices, zen_price
from inference import HttpResponse
from test_availability import free
from test_keeper_coder import HELLO, JSON_SCHEMA, ok, paid_state

COGNEE = 'cognee-token-0123456789'
PROBE = 'probe-token-0123456789a'


def consumers_state(tmp_path):
    state = paid_state(tmp_path)
    state['service_tokens'] = {'cognee': COGNEE, 'cognee-probe': PROBE}
    return state


def post(state, token, body, extra=None):
    return server.route('POST', '/v1/chat/completions', {'Authorization': 'Bearer ' + token, **(extra or {})},
                        'admin', json.dumps(body).encode(), state=state)


def usage_rows(state):
    return state['availability'].store.rows('SELECT * FROM av_usage ORDER BY id')


def set_price(state, model, **prices):
    with state['availability'].store.transaction() as db:
        for col, value in prices.items():
            db.execute('UPDATE av_models SET %s=? WHERE model=?' % col, (value, model))


def test_each_consumer_token_is_attributed_and_legacy_still_works(tmp_path):
    state = consumers_state(tmp_path)
    state['inference_transport'] = lambda m, u, h, p: ok(p['model'])
    assert post(state, COGNEE, HELLO)[0] == 200
    assert post(state, PROBE, HELLO)[0] == 200
    assert post(state, 'service', HELLO)[0] == 200
    assert post(state, 'nope-0123456789abcdef', HELLO)[0] == 401
    assert [r['consumer'] for r in usage_rows(state)] == ['cognee', 'cognee-probe', 'legacy']
    assert server.route('GET', '/api/v2/catalog', {'Authorization': 'Bearer ' + COGNEE}, 'admin', state=state)[0] == 403


def test_usage_row_carries_route_tokens_request_id_and_key(tmp_path):
    state = consumers_state(tmp_path)
    state['inference_transport'] = lambda m, u, h, p: ok(p['model'])
    post(state, COGNEE, {**HELLO, 'response_format': JSON_SCHEMA}, {'X-Request-Id': 'req-abc-123'})
    row = usage_rows(state)[0]
    assert (row['req_id'], row['provider'], row['model'], row['tier'], row['outcome']) == ('req-abc-123', 'p', 'b', 'free', 'ok')
    assert (row['prompt_tokens'], row['completion_tokens'], row['tokens_estimated']) == (10, 3, 0)
    assert row['credential_ref'].startswith('KEY') and row['attempts'] == 1


def test_missing_upstream_usage_is_estimated_and_flagged(tmp_path):
    state = consumers_state(tmp_path)
    state['inference_transport'] = lambda m, u, h, p: HttpResponse(200, {}, json.dumps(
        {'model': p['model'], 'choices': [{'message': {'content': 'x' * 40}}]}).encode())
    post(state, COGNEE, HELLO)
    row = usage_rows(state)[0]
    assert row['tokens_estimated'] == 1 and row['completion_tokens'] == 10 and row['prompt_tokens'] >= 1


def test_paid_cost_actual_and_free_shadow_from_sibling_or_fallback(tmp_path):
    state = consumers_state(tmp_path)
    set_price(state, 'pm', price_in=1e-6, price_out=4e-6)
    set_price(state, 'b', price_in=0.0, price_out=0.0, shadow_in=2e-6, shadow_out=8e-6)
    calls = []

    def http(m, u, h, p):
        calls.append(p['model'])
        return ok(p['model'])
    state['inference_transport'] = http
    post(state, COGNEE, HELLO)                      # served by free b (sibling shadow)
    free_row = usage_rows(state)[-1]
    assert free_row['cost_usd'] == 0 and free_row['shadow_cost_usd'] == pytest.approx(10 * 2e-6 + 3 * 8e-6)
    set_price(state, 'b', shadow_in=None, shadow_out=None)
    with state['availability'].store.transaction() as db:
        db.execute('UPDATE av_models SET shadow_in=NULL, shadow_out=NULL')
    post(state, COGNEE, HELLO)                      # no sibling -> paid fallback price
    assert usage_rows(state)[-1]['shadow_cost_usd'] == pytest.approx(10 * 1e-6 + 3 * 4e-6)
    state['inference_transport'] = lambda m, u, h, p: ok('pm') if p['model'] == 'pm' else HttpResponse(503, {}, b'{}')
    post(state, COGNEE, HELLO)                      # forced onto the paid fallback
    paid_row = usage_rows(state)[-1]
    assert paid_row['tier'] == 'paid' and paid_row['cost_usd'] == pytest.approx(10 * 1e-6 + 3 * 4e-6)


def test_upstream_reported_cost_wins(tmp_path):
    state = consumers_state(tmp_path)
    set_price(state, 'pm', price_in=1e-6, price_out=4e-6)
    state['inference_transport'] = lambda m, u, h, p: (HttpResponse(200, {}, json.dumps(
        {'model': 'pm', 'choices': [{'message': {'content': 'ok'}}],
         'usage': {'prompt_tokens': 10, 'completion_tokens': 3, 'cost': 0.5}}).encode())
        if p['model'] == 'pm' else HttpResponse(503, {}, b'{}'))
    post(state, COGNEE, HELLO)
    assert usage_rows(state)[-1]['cost_usd'] == 0.5


def test_failures_are_attributed_with_their_code(tmp_path):
    state = consumers_state(tmp_path)
    state['inference_transport'] = lambda *a: HttpResponse(503, {}, b'{}')
    post(state, COGNEE, HELLO)
    post(state, COGNEE, {**HELLO, 'model': 'gpt-x'})
    assert [r['outcome'] for r in usage_rows(state)] == ['no_working_compatible_free_model', 'use_keeper_coder_model']
    assert usage_rows(state)[0]['attempts'] >= 3


def test_metrics_expose_attribution_without_emails(tmp_path):
    state = consumers_state(tmp_path)
    set_price(state, 'b', shadow_in=2e-6, shadow_out=8e-6)
    state['inference_transport'] = lambda m, u, h, p: ok(p['model'])
    post(state, COGNEE, HELLO)
    text = '\n'.join(usage_metrics.lines(state))
    assert 'keeper_llm_requests_total{consumer="cognee",provider="p",model="b",tier="free",outcome="ok"} 1' in text
    assert 'keeper_llm_tokens_total{consumer="cognee",provider="p",model="b",tier="free",direction="prompt"} 10' in text
    assert 'basis="shadow"' in text and 'keeper_llm_latency_ms_bucket' in text
    assert 'keeper_connections{' in text and 'keeper_checks_total{kind="serve"' in text
    tiers = {l.split('tier="')[1].split('"')[0] for l in text.splitlines() if l.startswith('keeper_connections{')}
    assert tiers == {'free', 'paid'}
    assert '@' not in text.replace('@bao', '')  # no owner emails
    full = server.metrics_view(state)
    assert 'keeper_llm_requests_total' in full


def test_service_tokens_are_validated():
    with pytest.raises(ValueError):
        runtime.validate_service_tokens({'Cognee!': COGNEE}, ())
    with pytest.raises(ValueError):
        runtime.validate_service_tokens({'cognee': 'short'}, ())
    with pytest.raises(ValueError):
        runtime.validate_service_tokens({'a': COGNEE, 'b': COGNEE}, ())
    with pytest.raises(ValueError):
        runtime.validate_service_tokens({'cognee': COGNEE}, (COGNEE,))
    with pytest.raises(ValueError):
        runtime.validate_service_tokens({'legacy': COGNEE}, ())
    assert runtime.validate_service_tokens({'cognee': COGNEE}, ('admin',)) == {'cognee': COGNEE}


def test_access_record_and_span_carry_consumer_route_and_parent(monkeypatch):
    rec = server.http_access_record('t', 'r1', 'a' * 32, 'POST', '/v1/chat/completions', 200, 5,
                                    'service', 'fp', '', 'ua', 'cognee',
                                    server.served_fields([('X-Keeper-Model', 'b'), ('X-Keeper-Tier', 'free')]))
    assert rec['consumer'] == 'cognee' and rec['model'] == 'b' and rec['tier'] == 'free'
    assert server.http_parent_span({'traceparent': '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01'}) == 'b' * 16
    payload = tracing.span_payload('a' * 32, 'keeper.request', 1, 2, {'keeper.consumer': 'cognee'},
                                   parent_span_id='b' * 16, error=True)
    span = payload['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
    assert span['parentSpanId'] == 'b' * 16 and span['status']['code'] == 2


def test_discovery_keeps_numeric_prices_and_sibling_shadow():
    assert price_pair({'prompt': '0.000001', 'completion': '0.000004'}) == (1e-06, 4e-06)
    assert price_pair({'prompt': 'x'}) == (None, None)
    assert zen_price('$0.30') == pytest.approx(3e-7) and zen_price('Free') == 0.0 and zen_price('-') is None
    models = with_prices([free('v/m:free'), free('v/m')], {'v/m:free': (0.0, 0.0), 'v/m': (1e-6, 2e-6)})
    assert (models[0].shadow_in, models[0].shadow_out) == (1e-6, 2e-6) and models[1].price_in == 1e-6
    doc = '''## Endpoints
| Name | Model | Endpoint |
| Muse Free | muse-free | https://opencode.ai/zen/v1/chat/completions |
| Muse | muse | https://opencode.ai/zen/v1/chat/completions |
## Pricing
| Model | Input | Output |
| Muse Free | Free | Free |
| Muse | $1.00 | $3.00 |
'''
    by = {m.model: m for m in parse_zen(doc)}
    assert by['muse-free'].eligibility == 'free' and by['muse-free'].shadow_out == pytest.approx(3e-6)
    assert by['muse'].price_in == pytest.approx(1e-6)
