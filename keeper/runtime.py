"""Production availability wiring; explicit durable path, one worker per server."""
import os
import threading
from urllib.parse import urlsplit

import aa
from availability import Availability
from credentials import RuntimeCredentials
from discovery import CatalogDiscovery
from selection import Selector
from store import Store
from sweeps import Sweeps


def initialize(state, db_path, public_origin, service_token='', admin_tokens=()):
    origin = urlsplit(public_origin)
    if (not db_path or db_path == ':memory:' or not os.path.isabs(db_path)
            or origin.scheme != 'https' or not origin.netloc or origin.path
            or origin.query or origin.fragment or origin.username):
        raise ValueError('explicit durable database path and HTTPS PUBLIC_ORIGIN required')
    if service_token and service_token in (state['token'], *admin_tokens):
        raise ValueError('service principal must be separate from administrator')
    runtime = RuntimeCredentials(state['routes'])
    os.makedirs(os.path.dirname(db_path), mode=0o700, exist_ok=True)
    service = Availability(Store(db_path))
    service.sync_seeds(state['routes'])
    sweeps = Sweeps(service)
    state.update(availability=service, sweeps=sweeps,
                 selector=Selector(service, sweeps, runtime.resolve),
                 public_origin=public_origin, service_token=service_token,
                 build=os.environ.get('BUILD_ID', 'development'), aa_stale=True)
    return state


def start_worker(state):
    if state.get('worker_thread'):
        raise ValueError('worker already started')
    stop = threading.Event()
    def refresh():
        aa.refresh_state(state)
        CatalogDiscovery(state['availability']).refresh(state['routes'])
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
