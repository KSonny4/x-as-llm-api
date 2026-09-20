"""Authoritative negative pricing must invalidate cached transport aliases."""
from dataclasses import replace

import pytest

from availability import Model, Result
from discovery import CatalogDiscovery
from test_availability import free, seed, setup, succeed
from test_discovery import HTTP, response
from inference import HttpResponse
from zencli_bridge import ZenCLI, bridge_models


def zen_document(price):
    amount = {'free': 'Free', 'paid': '$1', 'unknown': '?', 'removed': '?'}[price]
    text = '''## Endpoints
| Model | Model ID | Endpoint |
| Nice | nice | `https://opencode.ai/zen/v1/chat/completions` |
| Anchor | anchor | `https://opencode.ai/zen/v1/chat/completions` |
## Pricing
| Model | Input | Output |
| Nice | %s | %s |
| Anchor | Free | Free |
''' % (amount, amount)
    if price == 'removed':
        text = '\n'.join(line for line in text.splitlines() if not line.startswith('| Nice |'))
    return HttpResponse(200, {}, text.encode())


@pytest.mark.parametrize('eligibility', ['paid', 'unknown', 'removed'])
@pytest.mark.parametrize('failed_keys', [1, 2])
def test_negative_zen_pricing_blocks_cached_bridge_despite_inventory_failure(
        tmp_path, eligibility, failed_keys):
    routes = [seed('opencode-zen', 'ONE'), seed('opencode-zen', 'TWO')]
    service, clock = setup(tmp_path, routes)
    catalog = {'data': [{'id': 'nice'}]}
    CatalogDiscovery(service, HTTP([zen_document('free'), response(catalog),
                                    response(catalog)]), bridge_enabled=True).refresh(routes)
    old = next(c for c in service.connections() if c['model'] == 'nice' and c['protocol'] == 'zencli')
    succeed(service, old)
    in_flight = service.begin_check(old['id'])
    clock.advance(10)
    replies = [zen_document(eligibility)]
    replies += [response(catalog)] * (2 - failed_keys)
    replies += [OSError('catalog unavailable')] * failed_keys
    CatalogDiscovery(service, HTTP(replies), bridge_enabled=True).refresh(routes)
    current = [c for c in service.connections() if c['model'] == 'nice']
    assert current and all(c['blocked_reason'] for c in current)
    assert not service.finish_check(in_flight, Result('working'))
    assert service.begin_check(old['id']) is None
    pushes = []
    def transport(method, url, headers, payload):
        pushes.append(payload)
        return HttpResponse(200, {}, b'{"ok":true}')
    ZenCLI(service, 'synthetic-internal', transport).sync()
    assert pushes[-1]['models'] == []
    assert any(h['state'] == 'working' and h['applied'] for h in service.history(old['id']))


def test_partial_modality_change_cannot_keep_old_text_route_free(tmp_path):
    routes = [seed('openrouter', 'ONE'), seed('openrouter', 'TWO')]
    service, clock = setup(tmp_path, routes)
    model = {'id': 'changing-model', 'pricing': {'prompt': '0', 'completion': '0'},
             'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']}}
    CatalogDiscovery(service, HTTP([response({'data': [model]})] * 2)).refresh(routes)
    old = next(c for c in service.connections() if c['model'] == model['id'])
    succeed(service, old)
    clock.advance(10)
    mixed = {**model, 'architecture': {'input_modalities': ['text'], 'output_modalities': ['text', 'audio']}}
    CatalogDiscovery(service, HTTP([response({'data': [mixed]}), OSError('unavailable')])).refresh(routes)
    current = next(c for c in service.connections() if c['id'] == old['id'])
    assert current['blocked_reason'] == 'eligibility_unknown'
    assert service.begin_check(old['id']) is None


def test_older_negative_evidence_cannot_overwrite_newer_free_bridge(tmp_path):
    service, clock = setup(tmp_path, [seed('opencode-zen')])
    direct = free('a', 'opencode-zen')
    service.update_catalog('opencode-zen', [direct, *bridge_models([direct])])
    prior = clock()
    clock.advance(20)
    service.update_catalog('opencode-zen', [direct, *bridge_models([direct])])
    service.update_catalog('opencode-zen', [replace(direct, eligibility='paid', verified_at=prior)], complete=False)
    assert all(c['blocked_reason'] == (None if c['protocol'] == 'zencli' else 'cli_required')
               for c in service.connections())


def test_partial_protocol_change_fences_prior_route(tmp_path):
    service, clock = setup(tmp_path)
    direct = free('a')
    service.update_catalog('p', [direct])
    old = service.connections()[0]
    ticket = service.begin_check(old['id'])
    clock.advance(1)
    service.update_catalog('p', [replace(direct, protocol='unsupported', eligibility='unknown')], complete=False)
    current = next(c for c in service.connections() if c['id'] == old['id'])
    assert current['blocked_reason'] == 'eligibility_unknown'
    assert not service.finish_check(ticket, Result('working'))


def test_negative_evidence_preserves_independent_provider_and_endpoint(tmp_path):
    service, clock = setup(tmp_path, [seed(), seed('other')])
    primary = free('a')
    alternate = replace(primary, base_url='https://independent.test/v1')
    service.update_catalog('p', [primary, alternate])
    service.update_catalog('other', [free('a', 'other')])
    clock.advance(10)
    service.update_catalog('p', [replace(primary, eligibility='paid')], complete=False)
    rows = service.connections()
    assert all(not c['blocked_reason'] for c in rows if c['model_id'] != primary.id)
    assert all(c['blocked_reason'] == 'paid' for c in rows if c['model_id'] == primary.id)
