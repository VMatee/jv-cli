"""Native auth deadline tests against a loopback synthetic service."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from windows_test_support import trusted_fixture_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli.transport import JvApiClient, JvClientConfig
if os.name == 'nt':
    from jvcli.platform._windows_auth import operation


class Expired(Exception):
    pass


@unittest.skipUnless(os.name == 'nt', 'Requires native owned auth processes')
class WindowsAuth(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='staging-auth-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        trusted_fixture_directory(self.root)
        for name in ('python.exe', f'python{sys.version_info.major}{sys.version_info.minor}.dll', 'python3.dll'):
            source = Path(sys.executable).parent / name
            if source.exists():
                shutil.copyfile(source, self.root / name)
        self.delay = 0
        self.returned = threading.Event()
        self.requests = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                owner.requests.append(self.path)
                if self.path.endswith('login'):
                    self.server.assertion = json.loads(body)['password'] == 'SYNTHETIC_PASSWORD'
                delay = owner.delay
                time.sleep(delay)
                try:
                    self.send_response(200 if self.path.endswith('login') else 204)
                    self.end_headers()
                    if self.path.endswith('login'):
                        self.wfile.write(b'{"access_token":"SYNTHETIC_TOKEN"}')
                except OSError:
                    pass
                finally:
                    owner.returned.set()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        self.client = JvApiClient(JvClientConfig(base_url=f'http://127.0.0.1:{server.server_port}'))

    def call(self, kind='login', seconds=3):
        operation(self.client, kind, seconds, Expired, root=self.root / 'state',
                  username='synthetic', password='SYNTHETIC_PASSWORD',
                  executable=str(self.root / 'python.exe'))

    def test_success_login_logout_no_persistence(self):
        self.call()
        self.assertEqual(self.client._token, 'SYNTHETIC_TOKEN')
        self.call('logout')
        self.assertIsNone(self.client._token)
        self.assertEqual(self.requests, ['/v1/auth/login', '/v1/auth/logout'])
        for path in (self.root / 'state').rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC_', path.read_bytes())

    def test_timeout_late_server_result_cannot_install_token(self):
        self.delay = .8
        with self.assertRaises(Expired):
            self.call(seconds=.3)
        self.assertIsNone(self.client._token)
        self.returned.wait(2)
        self.assertIsNone(self.client._token)
        self.delay = 0
        self.call()
        self.assertEqual(self.client._token, 'SYNTHETIC_TOKEN')

    def test_logout_timeout_cannot_clear_new_state(self):
        self.call()
        self.returned.clear()
        self.delay = .8
        with self.assertRaises(Expired):
            self.call('logout', seconds=.3)
        self.assertIsNone(self.client._token)
        self.client._token = 'NEW_SYNTHETIC_TOKEN'
        self.returned.wait(2)
        self.assertEqual(self.client._token, 'NEW_SYNTHETIC_TOKEN')

    def test_repeated_timeout_has_no_worker_threads(self):
        self.delay = .8
        for _ in range(3):
            with self.assertRaises(Expired):
                self.call(seconds=.3)
        self.assertIsNone(self.client._token)
        self.assertFalse([t for t in threading.enumerate()
                          if t.name in ('bridge-auth-io', 'bridge-pipe-io', 'jv-windows-job')])

    def test_bridge_recovers_after_timeout_then_shutdown(self):
        from jvcli import bridge, cli
        from jvcli.platform import _windows_auth as auth
        frames = []
        class Output:
            def emit(self, frame):
                frames.append(frame)
        b = bridge.Bridge(Output(), self.root, client_factory=lambda base: JvApiClient(JvClientConfig(base_url=base)))
        def isolated(client, kind, seconds, error, **kwargs):
            return operation(client, kind, seconds, error, **kwargs,
                             executable=str(self.root / 'python.exe'))
        def login(rid):
            b.request({'type': 'auth.login', 'request_id': rid,
                       'username': 'synthetic', 'password': 'SYNTHETIC_PASSWORD',
                       'base_url': self.client.base_url})
        with patch.object(auth, 'operation', isolated), patch.object(cli, 'STATE_DIR', self.root / 'bridge'), patch.object(bridge, 'AUTH_TIMEOUT', .3):
            self.delay = .8
            login('expired')
            self.assertIsNone(b.client)
            self.assertIsNone(b.account)
            self.assertIsNone(b.session)
            self.assertEqual(frames[-1]['code'], 'authentication_failed')
            self.assertTrue(self.returned.wait(2))
            self.assertIsNone(b.client)
            self.delay = 0
            with patch.object(bridge, 'AUTH_TIMEOUT', 3):
                login('success')
            self.assertEqual(frames[-1], {'type': 'auth.succeeded', 'request_id': 'success'})
            b.request({'type': 'bridge.shutdown', 'request_id': 'stop'})
            b.close()
        self.assertTrue(b.closed)
        self.assertIsNone(b.client)
        self.assertNotIn('SYNTHETIC_', json.dumps(frames))

    def test_timeout_releases_native_handles_and_excludes_argv_secrets(self):
        import ctypes as C
        import gc
        from jvcli.platform import _windows_fs as fs, _windows_auth as auth
        count = fs._api(fs.K, 'GetProcessHandleCount', fs.W.BOOL, fs.W.HANDLE, C.POINTER(fs.D))
        def handles():
            value = fs.D()
            fs._check(count(fs.W.HANDLE(-1), C.byref(value)))
            return value.value
        original = auth.OwnedProcess
        processes = []
        def spawn(command, env, **kwargs):
            self.assertNotIn('SYNTHETIC_', ' '.join(command))
            self.assertFalse(any('SYNTHETIC_' in v for v in env.values()))
            p = original(command, env, **kwargs)
            processes.append(p)
            return p
        self.delay = .8
        before = handles()
        with patch.object(auth, 'OwnedProcess', spawn):
            with self.assertRaises(Expired):
                self.call(seconds=.3)
        self.assertTrue(all(p.poll() is not None for p in processes))
        self.assertTrue(all(s.closed for p in processes for s in (p.stdin, p.stdout, p.stderr)))
        self.assertTrue(self.returned.wait(2))
        processes.clear()
        gc.collect()
        # Server-side accepted sockets have also finished by this point.
        time.sleep(.05)
        self.assertLessEqual(handles(), before + 1)

    def test_shutdown_queued_during_native_subprocess_auth(self):
        from jvcli.platform import windows
        self.delay = 1.2
        env = windows.isolated_env(self.root / 'subprocess')
        env['PYTHONHOME'] = sys.base_prefix
        env['JVCLI_HOME'] = str(self.root / 'bridge-state')
        process = windows.spawn_engine([str(self.root / 'python.exe'), '-B', '-s',
                                       str(ROOT / 'tests/fixtures/windows_auth_bridge.py')], env)
        requests = [
            {'type': 'auth.login', 'request_id': 'login', 'username': 'synthetic',
             'password': 'SYNTHETIC_PASSWORD', 'base_url': self.client.base_url},
            {'type': 'bridge.shutdown', 'request_id': 'stop'},
        ]
        stdout, stderr = process.communicate(''.join(json.dumps(r) + '\n' for r in requests), timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        frames = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual([f['type'] for f in frames], ['bridge.ready', 'request.error', 'bridge.stopping'])
        self.assertEqual(frames[1]['code'], 'authentication_failed')
        self.assertEqual(frames[2]['request_id'], 'stop')
        self.assertNotIn('SYNTHETIC_', stdout + stderr)
        self.assertTrue(self.returned.wait(2))


if __name__ == '__main__':
    unittest.main()
