"""Production availability wiring; explicit durable path, one worker per server."""
import os
import re
import threading
from urllib.parse import urlsplit

import aa
from availability import Availability
from credentials import RuntimeCredentials
from discovery import CatalogDiscovery
from selection import Selector
from store import Store
from sweeps import Sweeps


CONSUMER_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')


def validate_service_tokens(tokens, forbidden):
    """{consumer: token} for per-caller attribution. Names are low-cardinality
    metric labels; tokens must be distinct from each other and every other
    principal ('legacy'/'admin' are reserved for the shared/admin tokens)."""
    if not isinstance(tokens, dict):
        raise ValueError('KEEPER_SERVICE_TOKENS must be a JSON object')
    seen = set(t for t in forbidden if t)
    for name, token in tokens.items():
        if not isinstance(name, str) or not CONSUMER_NAME.match(name) or name in ('legacy', 'admin'):
            raise ValueError('invalid service consumer name')
        if not isinstance(token, str) or len(token) < 16 or token in seen:
            raise ValueError('service consumer tokens must be long and unique')
        seen.add(token)
    return dict(tokens)


def initialize(state, db_path, public_origin, service_token='', admin_tokens=(), zencli_token='',
               service_tokens=None):
    origin = urlsplit(public_origin)
    if (not db_path or db_path == ':memory:' or not os.path.isabs(db_path)
            or origin.scheme != 'https' or not origin.netloc or origin.path
            or origin.query or origin.fragment or origin.username):
        raise ValueError('explicit durable database path and HTTPS PUBLIC_ORIGIN required')
    if service_token and service_token in (state['token'], *admin_tokens):
        raise ValueError('service principal must be separate from administrator')
    if zencli_token and zencli_token in (state['token'], service_token, *admin_tokens):
        raise ValueError('internal bridge principal must be separate')
    consumers = validate_service_tokens(service_tokens or {},
                                        (state['token'], service_token, zencli_token, *admin_tokens))
    runtime = RuntimeCredentials(state['routes'])
    os.makedirs(os.path.dirname(db_path), mode=0o700, exist_ok=True)
    service = Availability(Store(db_path))
    service.sync_seeds(state['routes'])
    options = {}
    if zencli_token:
        from zencli_bridge import ZenCLI
        state['zencli'] = ZenCLI(service, zencli_token)
        options = {'verifier': state['zencli'].verify}
    else:
        # A disabled sidecar cannot inherit working evidence from a prior run.
        with service.store.transaction() as db:
            db.execute("UPDATE av_models SET present=0 WHERE protocol='zencli'")
    sweeps = Sweeps(service, lease_seconds=150 if zencli_token else 90, **options)
    if zencli_token:
        options['config_builder'] = state['zencli'].config
    state.update(availability=service, sweeps=sweeps,
                 selector=Selector(service, sweeps, runtime.resolve, **options),
                 public_origin=public_origin, service_token=service_token,
                 service_tokens=consumers,
                 build=os.environ.get('BUILD_ID', 'development'), aa_stale=True)
    return state


def start_worker(state):
    if state.get('worker_thread'):
        raise ValueError('worker already started')
    stop = threading.Event()
    def refresh():
        aa.refresh_state(state)
        CatalogDiscovery(state['availability'], bridge_enabled=bool(state.get('zencli'))).refresh(state['routes'])
        if state.get('zencli'):
            try:
                state['zencli'].sync()
                state['bridge_error'] = None
            except Exception:
                state['bridge_error'] = 'bridge_unavailable'
    def run():
        try:
            aa.refresh_state(state)
            state['sweeps'].run(stop, state['selector'].resolve_secret, refresh)
        except Exception:
            # Surface failure without logging potentially secret-bearing errors.
            state['worker_error'] = 'background_worker_failed'
    thread = threading.Thread(target=run, name='keeper-availability', daemon=True)
    state.update(worker_thread=thread, worker_stop=stop)
    thread.start()
    return stop
