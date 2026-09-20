import json
from test_api_v2 import state_for, call
from test_availability import free, seed


def test_dashboard_shell_has_no_provider_data_and_strict_assets(tmp_path):
    state, calls = state_for(tmp_path)
    code, body, headers = call(state, 'GET', '/')
    assert code == 200 and b'Accounts' in body and b'Models' in body
    assert b'dashboard.js' in body and b'synthetic-secret' not in body and b'example.test' not in body
    assert "default-src 'none'" in dict(headers)['Content-Security-Policy']
    assert not calls
    code, js, _ = call(state, 'GET', '/assets/dashboard.js')
    assert code == 200 and b'textContent' in js
    assert b'innerHTML' not in js and b'localStorage' not in js and b'sessionStorage' not in js
    assert call(state, 'GET', '/assets/../server.py')[0] == 404


def test_catalog_all_models_malicious_labels_and_polling(tmp_path):
    state, calls = state_for(tmp_path)
    s = state['availability']
    s.update_catalog('p', [free('m'+str(i)) for i in range(26)] + [free('<script>alert(1)</script>')])
    for _ in range(3):
        code, body, _ = call(state, 'GET', '/api/v2/catalog')
        models = json.loads(body)['models']
        assert len(models) >= 27 and any(m['model'].startswith('<script>') for m in models)
    assert not calls
