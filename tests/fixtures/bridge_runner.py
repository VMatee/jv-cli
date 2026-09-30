"""Internal injection harness. No public authentication/test bypass flag exists."""
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli import cli, bridge
from jvcli.safety import JvError

state = Path(os.environ['JVCLI_HOME'])

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
        if password != 'TEST_PASSWORD_DO_NOT_LEAK':
            raise JvError('TEST_PASSWORD_DO_NOT_LEAK TEST_TOKEN_DO_NOT_LEAK')
        self._token = 'TEST_TOKEN_DO_NOT_LEAK'
        record('login')
    def logout(self):
        record('logout')
        self._token = None

class FakeKeyRuntime(cli.AdapterRuntime):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.key = 'TEST_ADAPTER_KEY_DO_NOT_LEAK'
    def close(self):
        record('runtime.close')
        super().close()

# A mistakenly introduced network authentication path must fail the fixture.
def forbidden(*args, **kwargs):
    raise AssertionError('Network client is forbidden in this fixture')
socket.create_connection = forbidden
def fixture_engine():
    # Release ZIPs do not preserve executable mode for Python test assets.
    path = state / 'fixture-engine'
    path.write_bytes((ROOT / 'tests/fixtures/bridge_engine.py').read_bytes())
    path.chmod(0o700)
    return str(path)
cli._find_engine = fixture_engine
cli.AdapterRuntime = FakeKeyRuntime
original = bridge.serve
bridge.serve = lambda: original(client_factory=FakeClient)
raise SystemExit(cli.main(['bridge', '--stdio']))
