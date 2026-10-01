"""Internal injection harness. No public authentication/test bypass flag exists."""
import os
from pathlib import Path
import socket
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli import cli, bridge
from jvcli.safety import JvError

state = Path(os.environ['JVCLI_HOME'])
mode = os.environ.get('BRIDGE_FIXTURE', '')

def record(value):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / 'fixture-lifecycle').open('a') as f:
        f.write(value + '\n')

class FakeClient:
    _token = None
    def __init__(self, base):
        self.base_url = base
        record('client.created')
    def login(self, user, password):
        if user == 'slow-auth':
            time.sleep(5)
        if password != 'TEST_PASSWORD_DO_NOT_LEAK':
            raise JvError('TEST_PASSWORD_DO_NOT_LEAK TEST_TOKEN_DO_NOT_LEAK')
        self._token = 'TEST_TOKEN_DO_NOT_LEAK'
        record('login')
    def logout(self):
        record('logout')
        if mode == 'logout-failure':
            raise RuntimeError('TEST_TOKEN_DO_NOT_LEAK')
        self._token = None

class FakeKeyRuntime(cli.AdapterRuntime):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.key = 'TEST_ADAPTER_KEY_DO_NOT_LEAK'
    def close(self):
        record('runtime.close')
        super().close()
        if mode == 'context-failure':
            raise RuntimeError('TEST_ADAPTER_KEY_DO_NOT_LEAK')

# A mistakenly introduced network authentication path must fail the fixture.
def forbidden(*args, **kwargs):
    raise AssertionError('Network client is forbidden in this fixture')
socket.create_connection = forbidden
def fixture_engine():
    if mode == 'engine-missing':
        return None
    if mode == 'session-failure':
        raise OSError('TEST_PASSWORD_DO_NOT_LEAK')
    # Release ZIPs do not preserve executable mode for Python test assets.
    path = state / 'fixture-engine'
    path.write_bytes((ROOT / 'tests/fixtures/bridge_engine.py').read_bytes())
    path.chmod(0o700)
    return str(path)
cli._find_engine = fixture_engine
cli.AdapterRuntime = FakeKeyRuntime
bridge.AUTH_TIMEOUT = .2
if mode in ('worker-error', 'worker-hang', 'cleanup-slow'):
    def synthetic_turn(self, text, **options):
        if mode == 'worker-error':
            raise RuntimeError('TEST_PASSWORD_DO_NOT_LEAK TEST_TOKEN_DO_NOT_LEAK')
        if mode == 'worker-hang':
            threading.Event().wait(60)
        else:
            options['cancel_event'].wait(5)
            record('cleanup.started')
            time.sleep(.3)
        return 130
    cli.SessionRuntime.run_turn = synthetic_turn

original = bridge.serve
bridge.serve = lambda: original(client_factory=FakeClient)
raise SystemExit(cli.main(['bridge', '--stdio']))
