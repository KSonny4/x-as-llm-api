from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import time

import pytest
import server
from test_api_v2 import call


class CoordinatedSessions(dict):
    """Make the actual expiry/login race deterministic without network/sleeps."""
    def __init__(self, entries):
        super().__init__(entries)
        self.scanning = threading.Event()
        self.mutated = threading.Event()

    def items(self):
        iterator = iter(super().items())
        yield next(iterator)
        self.scanning.set()
        self.mutated.wait(0.25)
        yield from iterator

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.mutated.set()


@pytest.mark.parametrize('operation', ['login', 'logout'])
def test_session_expiry_and_concurrent_mutation_are_atomic(operation):
    state = server.make_state('admin')
    raw = 'synthetic-existing-session'
    sessions = CoordinatedSessions({'expired': 0,
        hashlib.sha256(raw.encode()).hexdigest(): time.time() + 60})
    state['sessions'] = sessions
    with ThreadPoolExecutor(max_workers=2) as pool:
        lookup = pool.submit(server._valid_session, state, raw)
        assert sessions.scanning.wait(2)
        if operation == 'login':
            mutation = pool.submit(call, state, 'POST', '/api/v1/session')
        else:
            mutation = pool.submit(call, state, 'POST', '/api/v1/session/logout', None,
                                   {'Authorization': 'Bearer admin', 'Cookie': server.SESSION_COOKIE + '=' + raw})
        assert lookup.result(timeout=3)
        assert mutation.result(timeout=3)[0] == 200
    assert 'expired' not in sessions
    assert len(sessions) == (2 if operation == 'login' else 0)
