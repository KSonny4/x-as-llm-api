import json
from availability import Availability, Model, Result
from credentials import RuntimeCredentials
from discovery import CatalogDiscovery
from inference import HttpResponse
from selection import Selector
from sweeps import Sweeps
from test_availability import setup, seed, free, succeed
from zencli_bridge import BRIDGE_BASE, ZenCLI, bridge_models


def fixture(tmp_path):
    routes=[seed('opencode-zen','ONE'),seed('opencode-zen','TWO')]
    s,clock=setup(tmp_path,routes)
    direct=free('a','opencode-zen')
    s.update_catalog('opencode-zen',[direct,*bridge_models([direct])])
    calls=[]
    def http(method,url,headers,payload):
        calls.append((method,url,headers,payload))
        if url.endswith('/internal/catalog'):return HttpResponse(200,{},b'{"ok":true}')
        return HttpResponse(200,{},json.dumps({'model':payload['model'],'choices':[{'message':{'content':'Hello'}}]}).encode())
    bridge=ZenCLI(s,'synthetic-internal',http)
    resolve=RuntimeCredentials(routes).resolve
    worker=Sweeps(s,provider_interval=0,key_interval=0,lease_seconds=150,verifier=bridge.verify)
    select=Selector(s,worker,resolve,verifier=bridge.verify,config_builder=bridge.config)
    return s,clock,bridge,select,calls


def test_cli_exact_identity_does_not_promote_direct_or_export_key(tmp_path):
    s,clock,bridge,select,calls=fixture(tmp_path)
    cli=next(c for c in s.connections() if c['protocol']=='zencli')
    result=select.select(cli['model_id'])
    assert result['error']=='not_exportable' and not calls
    config=select.select(cli['model_id'],export=False)
    selected=next(c for c in s.connections() if c['id']==config['connection_id'])
    assert selected['model_id']==cli['model_id'] and config['protocol']=='zencli'
    assert calls[-1][2]['X-Keeper-Provider-Key']=='synthetic-secret-'+selected['reference']
    assert calls[-1][2]['Authorization']=='Bearer synthetic-internal'
    assert calls[-1][3]['model']=='a'
    assert all(c['state']!='working' for c in s.connections() if c['protocol']!='zencli')
    assert 'synthetic-secret' not in '\n'.join(s.store.db.iterdump())


def test_dynamic_free_models_only_and_preserved_freshness():
    rows=[Model('opencode-zen','m'+str(i),'https://opencode.ai/zen/v1','openai','free','pricing',verified_at=123) for i in range(30)]
    rows += [Model('opencode-zen','paid','https://opencode.ai/zen/v1','openai','paid','pricing')]
    cli=bridge_models(rows)
    assert len(cli)==30 and all(m.protocol=='zencli' and m.base_url==BRIDGE_BASE and m.verified_at==123 for m in cli)


def test_bridge_catalog_and_text_only_capability(tmp_path):
    import service_wire as wire
    s,clock,bridge,selector,calls=fixture(tmp_path)
    req={'model':'keeper-coder','messages':[{'role':'system','content':'Be concise'},{'role':'user','content':'hello'}]}
    assert wire.compatible('zencli',req)
    for extra in [{'stream':True},{'max_tokens':64},{'tools':[]},{'temperature':0.2}]:
        assert not wire.compatible('zencli',{**req,**extra})
    bridge.sync()
    assert len(calls[0][3]['models'])==1 and calls[0][3]['models'][0]['model']=='a'
    clock.advance(86401)
    bridge.sync()
    assert calls[-1][3]['models']==[]


def test_real_go_sidecar_fake_cli_service_end_to_end(tmp_path):
    import os
    from pathlib import Path
    import shutil
    import socket
    import subprocess
    import time
    import urllib.error
    import urllib.request
    import pytest
    import server
    from test_api_v2 import call
    if not shutil.which('go'):pytest.skip('Go compiler unavailable')
    repo=Path(__file__).resolve().parent.parent
    binary=tmp_path/'zencli'
    gate=tmp_path/'sh'
    subprocess.run(['go','build','-ldflags=-X main.clockShellPath='+str(gate),'-o',str(binary),'.'],cwd=repo/'zencli',check=True,capture_output=True)
    gate.symlink_to(binary)
    fake=tmp_path/'opencode'
    fake.write_text("#!/bin/sh\nprintf '%s\\n' '{\"type\":\"text\",\"part\":{\"text\":\"Hello from isolated CLI\"}}' '{\"type\":\"step_finish\",\"part\":{\"reason\":\"stop\"}}'\n")
    fake.chmod(0o700)
    import tempfile
    import functools
    import zencli_bridge
    ipc_dir=tempfile.TemporaryDirectory(prefix='keeper-ipc-',dir='/tmp')
    socket_path=ipc_dir.name+'/private/http.sock'
    process=subprocess.Popen([str(binary),'-socket',socket_path,'-opencode-bin',str(fake)],env={'KEEPER_ZENCLI_TOKEN':'synthetic-internal'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        http=functools.partial(zencli_bridge.unix_request,socket_path=socket_path)
        for _ in range(50):
            try:
                if http('POST',BRIDGE_BASE.removesuffix('/v1')+'/internal/catalog',{},{}).status==401:break
            except OSError:time.sleep(0.05)
        else:raise AssertionError('sidecar did not start')
        s,clock,bridge,selector,calls=fixture(tmp_path)
        clock.value=time.time()
        with s.store.transaction() as db:db.execute('UPDATE av_models SET checked_at=?',(clock(),))
        bridge.transport=http
        cli=next(c for c in s.connections() if c['protocol']=='zencli')
        assert selector.select(cli['model_id'],export=False)['protocol']=='zencli'
        state=server.make_state('admin')
        state.update(availability=s,selector=selector,sweeps=selector.sweeps,zencli=bridge,service_token='service')
        code,raw,_=call(state,'POST','/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'system','content':'Be concise'},{'role':'user','content':'Hi'}]}, {'Authorization':'Bearer service'})
        assert code==200 and json.loads(raw)['choices'][0]['message']['content']=='Hello from isolated CLI'
        assert b'synthetic-' not in raw
        assert call(state,'POST','/api/v2/credentials',{'model_id':cli['model_id']})[0]==409
        assert call(state,'POST','/v1/chat/completions',{'model':'keeper-coder','messages':[{'role':'user','content':'Hi'}],'stream':True},{'Authorization':'Bearer service'})[0]==503
        assert all(c['state']!='working' for c in s.connections() if c['protocol']!='zencli')
    finally:
        process.terminate();process.wait(timeout=5);ipc_dir.cleanup()


def test_unix_logical_authority_and_no_old_loopback_success(tmp_path):
    import time
    from availability import blocked_reason
    s,clock,bridge,selector,calls=fixture(tmp_path)
    assert BRIDGE_BASE=='http://keeper-zencli/v1'
    old=Model('opencode-zen','a','http://127.0.0.1:8099/v1','zencli','unknown','old')
    with s.store.transaction() as db:
        s._put_model(db,old)
        s._expand(db)
        db.execute("UPDATE av_models SET eligibility='free' WHERE id=?",(old.id,))
        db.execute("UPDATE av_connections SET state='working',checked_at=? WHERE model_id=?",(clock(),old.id))
    rows=s.connections()
    assert all(c['blocked_reason'] for c in rows if c['model_id']==old.id)
    assert all(c['state']=='unknown' and c['checked_at'] is None for c in rows if c['protocol']=='zencli' and c['model_id']!=old.id)
    assert selector.select(old.id,export=False)['error']=='no_working_connection'
    assert 'Historical CLI endpoint' in next(m for m in s.catalog()['models'] if m['id']==old.id)['transport_note']


def test_unix_http_client_no_dns_redirect_proxy_or_unbounded_body(monkeypatch):
    import http.server
    import socket
    import socketserver
    import tempfile
    import threading
    import pytest
    from zencli_bridge import unix_request
    calls=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            calls.append((self.path,self.headers.get('Authorization')))
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            self.send_response(302 if len(calls)==1 else 200)
            self.send_header('Location','https://must-not-follow.invalid/')
            self.end_headers()
            self.wfile.write(b'redirect' if len(calls)==1 else b'x'*(1024*1024+1))
    def no_dns(*args): raise AssertionError('Unix IPC performed DNS lookup')
    monkeypatch.setattr(socket,'getaddrinfo',no_dns)
    monkeypatch.setenv('HTTP_PROXY','http://must-not-proxy.invalid')
    with tempfile.TemporaryDirectory(prefix='keeper-unix-',dir='/tmp') as directory:
        path=directory+'/http.sock'
        server=socketserver.UnixStreamServer(path,Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=BRIDGE_BASE+'/chat/completions'
            response=unix_request('POST',url,{'Authorization':'Bearer synthetic-internal'},{},socket_path=path)
            assert response.status==302 and len(calls)==1
            with pytest.raises(ValueError,match='too large'):
                unix_request('POST',url,{}, {},socket_path=path)
            with pytest.raises(ValueError,match='fixed bridge endpoint'):
                unix_request('POST','http://127.0.0.1:8099/v1/chat/completions',{}, {},socket_path=path)
            assert calls[0]==('/v1/chat/completions','Bearer synthetic-internal')
            assert len(calls)==2
        finally:
            server.shutdown();server.server_close();thread.join()
