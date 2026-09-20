import json
import threading
import urllib.request
from unittest.mock import patch

import server
from test_api_v2 import state_for


def test_runtime_requires_explicit_database_and_separate_principal(tmp_path):
    from runtime import initialize
    state=server.make_state('admin')
    import pytest
    with pytest.raises(ValueError):initialize(state, '', 'https://keeper.example', 'service')
    with pytest.raises(ValueError):initialize(state,str(tmp_path/'db'),'https://keeper.example','admin')
    initialize(state,str(tmp_path/'db'),'https://keeper.example','service')
    assert state['availability'].store.rows('PRAGMA integrity_check')[0]['integrity_check']=='ok'
    assert state['service_token']=='service'


def test_real_http_auth_csrf_and_stream_headers(tmp_path):
    state,_=state_for(tmp_path)
    from test_availability import succeed
    for c in state['availability'].connections():succeed(state['availability'],c)
    state['stream_transport']=lambda config,payload: iter([
      {'model':config['model'],'choices':[{'index':0,'delta':{'content':'hello'},'finish_reason':None}]},
      {'model':config['model'],'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}])
    class Handler(server.H):pass
    Handler.state=state;Handler.token='admin'
    http=server.KeeperHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    root='http://127.0.0.1:'+str(http.server_port)
    try:
        req=urllib.request.Request(root+'/v1/chat/completions',data=json.dumps({'model':'keeper-coder','messages':[{'role':'user','content':'hello'}],'stream':True}).encode(),headers={'Authorization':'Bearer service'})
        with urllib.request.urlopen(req) as res:
            assert res.headers['Content-Type']=='text/event-stream'
            assert res.headers.get('Content-Length') is None
            assert b'hello' in res.read() and res.status==200
        with urllib.request.urlopen(urllib.request.Request(root+'/api/v2/catalog',headers={'Authorization':'Bearer admin'})) as res:
            assert b'synthetic-secret' not in res.read()
    finally:
        http.shutdown();http.server_close();thread.join()


def test_legacy_matrix_uses_exact_authoritative_proof_without_network(tmp_path):
    state,_=state_for(tmp_path)
    state['probe']={'bogus':'ok'}
    from test_api_v2 import call
    with patch('server.enumerate_inventory',side_effect=AssertionError('network')):
        code,raw,_=call(state,'GET','/api/v1/matrix')
    assert code==200
    assert all(cell['state']!='ok' for row in json.loads(raw)['rows'] for cells in row['cells'].values() for cell in cells)


def test_legacy_ingest_does_not_fan_out_or_persist_arbitrary_secret_text(tmp_path):
    from test_availability import seed
    state=server.make_state('admin',{'routes':[seed(connection_id='one'),seed(key='KEY2',connection_id='two')]},feedback_log=str(tmp_path/'feedback'))
    doc={'provider':'p','model':'a','state':'ok','detail':{'l1':'ok','l2':'synthetic-secret-KEY1'},'checked_at':'2026-09-20T00:00:00Z'}
    assert not server.ingest_probe(state,doc)[0]
    assert not state['probe']
    assert server.ingest_probe(state,{**doc,'connection_id':'one'})[0]
    assert 'synthetic-secret' not in json.dumps(state['probe_detail'])
    server.spool_feedback(state,{'provider':'p','model':'a','errorClass':'auth','httpStatus':401,'keeperPackVersion':'v2','message':'synthetic-secret-KEY1'})
    assert 'synthetic-secret' not in (tmp_path/'feedback').read_text()


def test_production_legacy_health_and_keyqueue_cannot_show_old_cli_success(tmp_path):
    from test_api_v2 import call
    state,_=state_for(tmp_path)
    state['probe']={'bogus':'ok'}
    assert 'bogus' not in json.loads(call(state,'GET','/api/v1/health')[1])['routes']
    queue=json.loads(call(state,'GET','/api/v1/key-queue')[1])
    assert len(queue['keys'])==2 and all(k['state']=='unknown' for k in queue['keys'])
