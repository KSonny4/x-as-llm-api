import json

import server
from test_api_v2 import call
from test_availability import succeed
from test_zencli_bridge import fixture


def test_bridge_success_is_never_labelled_direct_in_legacy_views(tmp_path):
    service, _, _, _, _ = fixture(tmp_path)
    cli = next(c for c in service.connections() if c['protocol'] == 'zencli')
    succeed(service, cli)
    state = server.make_state('admin')
    state['availability'] = service
    for path in ('/api/v1/health', '/api/v1/key-queue', '/api/v1/matrix'):
        code, raw, _ = call(state, 'GET', path)
        assert code == 200
        doc = json.loads(raw)
        assert doc['evidence'] == 'exact_transport'
        if path == '/api/v1/health':
            assert doc['route_protocols'][cli['id']] == 'zencli'
        elif path.endswith('key-queue'):
            key = next(k for k in doc['keys'] if k['name'] == cli['reference'])
            assert key['working_transports'] == ['zencli']
        else:
            cells = [c for row in doc['rows'] for entries in row['cells'].values() for c in entries]
            entry = next(c for c in cells if c['connection_id'] == cli['id'])
            assert entry['protocol'] == 'zencli' and entry['l1'] == 'not-run' and entry['l2'] == 'ok'
            assert all(c['l1'] != 'ok' for c in cells)
