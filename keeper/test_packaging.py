import json
import os
import re
from pathlib import Path
import subprocess
import threading

import server
from test_api_v2 import state_for


def test_docker_copies_all_runtime_assets_and_durable_nomad_bind():
    root=Path(__file__).resolve().parent
    docker=(root/'Dockerfile').read_text()
    for name in ['runtime.py','aa.py','aa_match.py','availability.py','store.py','selection.py','service_api.py','service_wire.py','dashboard.html','dashboard.js','dashboard.css','legacy_view.py']:
        assert name in docker
    nomad=(root.parent/'keeper.nomad.hcl').read_text()
    assert 'AVAILABILITY_DB' in nomad and '/var/lib/keeper/availability.db' in nomad
    assert 'KEEPER_SERVICE_TOKEN' in nomad and 'PUBLIC_ORIGIN' in nomad
    assert 'volumes' in nomad and 'var.keeper_data_path' in nomad
    assert re.search(r'PROBE_DB\s*=\s*"/var/lib/keeper/probe.db"', nomad)


def test_docker_copies_every_keeper_module_the_server_imports():
    import sys
    import runtime, service_api  # noqa: F401  (import graph of the served app)
    root=Path(__file__).resolve().parent
    copied=set(re.findall(r'[\w.-]+\.py', (root/'Dockerfile').read_text()))
    local={Path(m.__file__).name for m in list(sys.modules.values())
           if getattr(m,'__file__',None) and Path(m.__file__).resolve().parent==root
           and not Path(m.__file__).name.startswith(('test_','conftest'))}
    assert 'zencli_structured.py' in local and local <= copied, sorted(local-copied)


def test_sidecar_nomad_uses_supported_tmpfs_mount():
    import shutil
    import pytest
    if not shutil.which('nomad'):
        pytest.skip('Nomad CLI needed for HCL rendering')
    root = Path(__file__).resolve().parents[1]
    args = ['nomad', 'job', 'run', '-output']
    for key in ('keeper_token', 'keeper_service_token', 'keeper_zencli_token', 'keeper_image', 'zencli_image'):
        args.append('-var=' + key + '=synthetic-' + key)
    job = json.loads(subprocess.check_output(args + ['keeper.nomad.hcl'], cwd=root))['Job']
    task = next(t for t in job['TaskGroups'][0]['Tasks'] if t['Name'] == 'zencli')
    config = task['Config']
    assert 'tmpfs' not in config  # Docker CLI option, NOT a Nomad driver field.
    mount = config['mount'][0]
    assert mount['type'] == 'tmpfs' and mount['target'] == '/tmp'
    assert mount['tmpfs_options'][0] == {'size': 536870912, 'mode': 1023}
    assert config['readonly_rootfs'] and config['cap_drop'] == ['ALL']
    assert config['security_opt'] == ['no-new-privileges']
    assert not config.get('volumes')
    assert config['network_mode']=='bridge' and not config.get('ports')
    assert task['Env']['KEEPER_ZENCLI_SOCKET']=='/alloc/data/keeper-zencli/http.sock'
    assert all(p['Label']!='zencli' for n in job['TaskGroups'][0]['Networks'] for p in n.get('ReservedPorts',[]))


def test_fake_provider_smoke_end_to_end_redacts_and_never_feedbacks_live_by_default(tmp_path):
    state,_=state_for(tmp_path)
    from test_availability import succeed
    for c in state['availability'].connections():succeed(state['availability'],c)
    state['inference_transport']=state['selector'].transport
    class Handler(server.H):pass
    Handler.state=state;Handler.token='admin'
    http=server.KeeperHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    env={**os.environ,'BASE':'http://127.0.0.1:'+str(http.server_port),'KEEPER_TOKEN':'admin',
         'KEEPER_SERVICE_TOKEN':'service','SMOKE_FIXTURE':'synthetic-only','SMOKE_FAKE_FEEDBACK':'1','SMOKE_CHECKS':'1',
         'SMOKE_INFERENCE':'1','SMOKE_MODEL_ID':state['availability'].connections()[0]['model_id']}
    try:
        proc=subprocess.run(['python3','smoke.py'],env=env,capture_output=True,timeout=30)
        assert proc.returncode==0,proc.stdout.decode()
        assert b'SMOKE GREEN' in proc.stdout
        assert b'synthetic-secret' not in proc.stdout+proc.stderr
        assert state['availability'].store.rows('SELECT * FROM av_feedback')
    finally:
        http.shutdown();http.server_close();thread.join()
