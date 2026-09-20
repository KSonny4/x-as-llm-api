import json
import server
from test_selection import fixture


def state_for(tmp_path):
    service, clock, selector, calls = fixture(tmp_path)
    state = server.make_state('admin')
    state.update(availability=service, selector=selector, sweeps=selector.sweeps,
                 public_origin='https://keeper.example', service_token='service')
    return state, calls


def call(state, method, path, data=None, headers=None):
    return server.route(method, path, headers or {'Authorization': 'Bearer admin'}, 'admin',
                        json.dumps(data).encode() if data is not None else None, state=state)


def test_authenticated_secret_free_catalog_and_exact_credentials(tmp_path):
    state, calls = state_for(tmp_path)
    assert call(state, 'GET', '/api/v2/catalog', headers={'X': 'none'})[0] == 401
    code, body, headers = call(state, 'GET', '/api/v2/catalog')
    assert code == 200 and b'synthetic-secret' not in body and not calls
    model = json.loads(body)['models'][0]
    code, body, headers = call(state, 'POST', '/api/v2/credentials', {'model_id': model['id']})
    assert code == 200 and json.loads(body)['model'] == model['model']
    assert 'no-store' in dict(headers)['Cache-Control']
    assert call(state, 'POST', '/api/v2/credentials', {'model_id': 'missing', 'endpoint': 'https://evil'})[0] == 422


def test_session_csrf_origin_and_bearer_only_legacy_values(tmp_path):
    state, calls = state_for(tmp_path)
    _, _, headers = call(state, 'POST', '/api/v1/session')
    cookie = dict(headers)['Set-Cookie'].split(';')[0]
    browser = {'Cookie': cookie}
    code, body, _ = call(state, 'GET', '/api/v2/session', headers=browser)
    assert code == 200 and b'admin' not in body
    csrf = json.loads(body)['csrf']
    assert call(state, 'POST', '/api/v2/checks', {}, browser)[0] == 403
    good = {**browser, 'Origin': 'https://keeper.example', 'X-Keeper-CSRF': csrf}
    assert call(state, 'POST', '/api/v2/checks', {}, good)[0] == 202
    assert call(state, 'POST', '/api/v2/checks', {}, {**good, 'Origin': 'https://evil'})[0] == 403
    assert call(state, 'GET', '/packs', headers=browser)[0] == 401
    assert call(state, 'GET', '/v1/route/a', headers=browser)[0] == 401
    assert call(state, 'POST', '/feedback', {}, good)[0] == 401


def test_precise_feedback_redaction_and_unknown_ids(tmp_path):
    state, calls = state_for(tmp_path)
    service = state['availability']
    cell = service.connections()[0]
    code, body, _ = call(state, 'POST', '/api/v2/feedback', {'connection_id': cell['id'], 'reason': 'synthetic-secret'})
    assert code == 200 and json.loads(body)['connection_id'] != cell['id']
    assert service.feedback(cell['id'])[0]['reason'] == 'client_failure'
    assert call(state, 'POST', '/api/v2/feedback', {'connection_id': 'missing'})[0] == 404
    assert call(state, 'POST', '/api/v2/checks', {'credential_id': 'missing'})[0] == 404
    assert call(state, 'POST', '/api/v2/checks', [1])[0] == 422
