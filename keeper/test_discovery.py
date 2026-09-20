import json

from availability import Availability
from discovery import CatalogDiscovery, parse_zen, parse_gemini_pricing
from inference import HttpResponse
from test_availability import setup, seed, free


def response(doc):
    return HttpResponse(200, {}, json.dumps(doc).encode())


class HTTP:
    def __init__(self, docs):
        self.docs = list(docs)
        self.calls = []
    def __call__(self, method, url, headers, payload=None):
        self.calls.append((method, url, headers, payload))
        item = self.docs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_priced_catalog_paginated_each_key_no_cap_and_missing_price(tmp_path):
    routes = [seed('openrouter', 'K1'), seed('openrouter', 'K2')]
    s, _ = setup(tmp_path, routes)
    page = {'data': [{'id': 'm' + str(i), 'architecture': {'input_modalities':['text'], 'output_modalities':['text']}, 'pricing': {'prompt': '0', 'completion': '0'}} for i in range(25)],
            'next_page_token': 'page2'}
    tail = {'data': [{'id': 'paid', 'architecture': {'input_modalities':['text'], 'output_modalities':['text']}, 'pricing': {'prompt': '0.001', 'completion': '0'}},
                     {'id': 'unknown'}, {'id': 'fee', 'architecture': {'input_modalities':['text'], 'output_modalities':['text']}, 'pricing': {'prompt': '0', 'completion': '0', 'request': '0.1'}}]}
    http = HTTP([response(page), response(tail), response({'data': [{'id': 'key2-only', 'architecture': {'input_modalities':['text'], 'output_modalities':['text']}, 'pricing': {'prompt': '0', 'completion': '0'}}]})])
    CatalogDiscovery(s, http).refresh(routes)
    rows = s.connections()
    assert len([c for c in rows if not c['blocked_reason']]) == 52
    assert not any(c['eligibility'] == 'free' for c in rows if c['model'] in ('paid', 'unknown', 'fee'))
    assert len(http.calls) == 3
    assert http.calls[0][2]['Authorization'] != http.calls[2][2]['Authorization']
    assert 'page_token=page2' in http.calls[1][1]


def test_failure_preserves_catalog_with_error_and_original_freshness(tmp_path):
    routes = [seed('openrouter')]
    s, clock = setup(tmp_path, routes)
    good = {'data': [{'id': 'free', 'architecture': {'input_modalities':['text'], 'output_modalities':['text']}, 'pricing': {'prompt': '0', 'completion': '0'}}]}
    discovery = CatalogDiscovery(s, HTTP([response(good), RuntimeError('synthetic-secret-KEY1')]))
    discovery.refresh(routes)
    timestamp = next(c['catalog_checked_at'] for c in s.connections() if c['model'] == 'free')
    clock.advance(10)
    discovery.refresh(routes)
    c = next(c for c in s.connections() if c['model'] == 'free')
    assert c['catalog_checked_at'] == timestamp and c['eligibility'] == 'free'
    status = s.store.rows('SELECT * FROM av_discovery')[0]
    assert status['error'] == 'discovery_failed'
    assert 'synthetic-secret' not in str(status)


def test_zen_documented_price_join_exact_route_and_nontext():
    text = '''## Endpoints
| Model | Model ID | Endpoint | SDK |
| Nice | nice | `https://opencode.ai/zen/v1/responses` | sdk |
| Nontext | nontext | `https://opencode.ai/zen/v1/systemone` | - |
| Paid Free Name | paid-free | `https://opencode.ai/zen/v1/chat/completions` | sdk |
## Pricing
| Model | Input | Output | Cached Read |
| Nice | Free | Free | Free |
| Nontext | Free | Free | - |
| Paid Free Name | $1 | $2 | - |
'''
    models = {m.model: m for m in parse_zen(text)}
    assert models['nice'].protocol == 'responses'
    assert models['nice'].eligibility == 'free'
    assert models['nontext'].protocol == 'unsupported'
    assert models['paid-free'].eligibility == 'paid'


def test_gemini_recurring_allowance_needs_verified_account_tier(tmp_path):
    html = '''<h2 id="gemini-free">Free</h2><em><code>gemini-free</code></em>
<table><tr><th></th><th>Free Tier</th><th>Paid Tier</th></tr>
<tr><td>Input price</td><td>Free of charge</td><td>$2</td></tr>
<tr><td>Output price</td><td>Free of charge</td><td>$5</td></tr></table>
<h2 id="gemini-paid">Paid</h2><code>gemini-paid</code>
<table><tr><th></th><th>Free Tier</th></tr>
<tr><td>Input price</td><td>Not available</td></tr>
<tr><td>Output price</td><td>Not available</td></tr></table>'''
    assert parse_gemini_pricing(html) == {'gemini-free'}
    routes = [seed('gemini', 'FREE', free_tier=True, no_paid_fallback=True, tier_provenance='operator:billing-disabled'),
              seed('gemini', 'UNKNOWN')]
    s, _ = setup(tmp_path, routes)
    from availability import Model
    s.update_catalog('gemini', [Model('gemini', 'gemini-free', 'https://generativelanguage.googleapis.com/v1beta',
                                    'gemini', 'free', 'https://ai.google.dev/gemini-api/docs/pricing', True)])
    rows = [c for c in s.connections() if c['model'] == 'gemini-free']
    assert next(c for c in rows if c['reference'] == 'FREE')['blocked_reason'] is None
    assert next(c for c in rows if c['reference'] == 'UNKNOWN')['state'] == 'free_tier_unverified'


def test_unknown_cli_missing_eligibility_and_disabled_accounted(tmp_path):
    routes = [seed(), seed(key='CLI'), seed(key='OFF', active=False)]
    routes[1]['wire'] = 'none'; routes[1].pop('api_key')
    s, _ = setup(tmp_path, routes)
    CatalogDiscovery(s, HTTP([])).refresh(routes)
    assert {c['state'] for c in s.connections()} == {'eligibility_unknown', 'unsupported', 'disabled'}


def test_multiple_api_routes_and_verified_seed_pricing_survive_id_only_inventory(tmp_path):
    first = seed(model='explicit', free_eligibility={
        'kind': 'zero_price', 'provenance': 'https://provider.test/pricing', 'verified_at': 1_800_000_000})
    second = seed(model='elsewhere'); second['base_url'] = 'https://other.test/v1'
    routes = [first, second]
    s, _ = setup(tmp_path, routes)
    http = HTTP([response({'data': [{'id': 'explicit'}]}), response({'data': [{'id': 'elsewhere'}]})])
    CatalogDiscovery(s, http).refresh(routes)
    assert len(http.calls) == 2
    assert next(c for c in s.connections() if c['model'] == 'explicit')['eligibility'] == 'free'
    assert next(c for c in s.connections() if c['model'] == 'elsewhere')['state'] == 'eligibility_unknown'


def test_catalog_cannot_reflect_credentials_into_sqlite_or_status(tmp_path):
    routes = [seed('openrouter')]
    s, _ = setup(tmp_path, routes)
    http = HTTP([response({'data': [{'id': 'echo-synthetic-secret-KEY1',
                                   'pricing': {'prompt': '0', 'completion': '0'}}]})])
    CatalogDiscovery(s, http).refresh(routes)
    assert 'synthetic-secret' not in json.dumps(s.catalog())
    assert 'synthetic-secret' not in '\n'.join(s.store.db.iterdump())


def test_zero_token_prices_do_not_authorize_audio_or_mixed_output_spend(tmp_path):
    from sweeps import Sweeps
    routes=[seed('openrouter')]
    s,_=setup(tmp_path,routes)
    entries=[{'id':name,'pricing':{'prompt':'0','completion':'0'},
              'architecture':{'input_modalities':['text'],'output_modalities':outputs}}
             for name,outputs in [('audio-only',['audio']),('lyria-priced-song',['text','audio']),('text-safe',['text'])]]
    entries.append({'id':'missing-modalities','pricing':{'prompt':'0','completion':'0'}})
    CatalogDiscovery(s,HTTP([response({'data':entries})])).refresh(routes)
    cells={c['model']:c for c in s.connections()}
    assert cells['text-safe']['blocked_reason'] is None
    for name in ['audio-only','lyria-priced-song','missing-modalities']:
        assert cells[name]['eligibility']=='unknown' and cells[name]['blocked_reason']=='eligibility_unknown'
    worker=Sweeps(s)
    assert worker.progress(worker.schedule())['total']==1


def test_modality_uncertainty_supersedes_old_free_even_partial_or_explicit(tmp_path):
    from availability import Model
    routes=[seed('openrouter','K1',model='lyria',free_eligibility={'kind':'zero_price','provenance':'old-proof','verified_at':1800000000}),seed('openrouter','K2')]
    for route in routes: route['base_url']='https://openrouter.ai/api/v1'
    s,clock=setup(tmp_path,routes)
    row={'id':'lyria','pricing':{'prompt':'0','completion':'0'},'architecture':{'input_modalities':['text'],'output_modalities':['text','audio']}}
    http=HTTP([response({'data':[row]}),RuntimeError('provider unavailable')])
    CatalogDiscovery(s,http).refresh(routes)
    assert all(c['eligibility']=='unknown' for c in s.connections() if c['model']=='lyria' and c['base_url']=='https://openrouter.ai/api/v1')
