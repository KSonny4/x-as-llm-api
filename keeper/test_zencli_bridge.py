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
    subprocess.run(['go','build','-o',str(binary),'.'],cwd=repo/'zencli',check=True,capture_output=True)
    fake=tmp_path/'opencode'
    fake.write_text("#!/bin/sh\nprintf '%s\\n' '{\"type\":\"text\",\"part\":{\"text\":\"Hello from isolated CLI\"}}' '{\"type\":\"step_finish\",\"part\":{\"reason\":\"stop\"}}'\n")
    fake.chmod(0o700)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([str(binary),'-port',str(port),'-opencode-bin',str(fake)],env={'KEEPER_ZENCLI_TOKEN':'synthetic-internal'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        def http(method,url,headers,payload):
            from urllib.parse import urlsplit
            req=urllib.request.Request('http://127.0.0.1:'+str(port)+urlsplit(url).path,headers=headers,data=json.dumps(payload).encode(),method=method)
            try:res=urllib.request.urlopen(req,timeout=5)
            except urllib.error.HTTPError as exc:res=exc
            with res:return HttpResponse(res.code,dict(res.headers),res.read())
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
        process.terminate();process.wait(timeout=5)
