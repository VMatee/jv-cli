"""Disposable installer + installed public bridge acceptance, no production access.

The outer runner may use developer Python. Every app launch uses installed
jvcli.exe, and the inner runner uses embedded Python with isolated module paths.
Only test fixtures are read from this checkout; all jvcli modules must be bundled.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip().encode('ascii')


def inner(app, node):
    # The embedded _pth must resolve jvcli BEFORE test utilities add test paths.
    import jvcli.cli as installed_cli
    if not Path(installed_cli.__file__).resolve().is_relative_to(app):
        raise RuntimeError('Source-tree import leakage')
    sys.path.extend([str(ROOT / 'scripts'), str(ROOT / 'tests')])
    from jvcli.platform import windows
    from windows_trusted_acceptance import TrustedAcceptance
    from test_windows_auth import WindowsAuth, Expired, operation
    installed_python = str(app / 'python/python.exe')
    engine = windows.find_engine(app / 'runtime')
    if installed_cli._version_of_engine(engine) != '0.149.1':
        raise RuntimeError('Installed engine is not pinned')

    class InstalledBridge(TrustedAcceptance):
        launcher = app / 'jvcli.exe'
        tool_python = installed_python

        def test_installed_network_matrix(self):
            process = self.start()
            self.login(process)
            self.session(process)
            for family, address in ((socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')):
                for tool in ('powershell', 'python', 'node'):
                    with self.subTest(family=family, tool=tool):
                        with socket.socket(family) as listener:
                            listener.bind((address, 0)); listener.listen(); listener.settimeout(20)
                            port = listener.getsockname()[1]
                            received, errors = [], []
                            def accept():
                                try:
                                    conn, _ = listener.accept()
                                    with conn:
                                        received.append(True)
                                        conn.sendall(b'x')
                                except Exception as exc:
                                    errors.append(type(exc).__name__)
                            thread = threading.Thread(target=accept)
                            thread.start()
                            if tool == 'powershell':
                                af = 'InterNetwork' if family == socket.AF_INET else 'InterNetworkV6'
                                command = f"$c=New-Object Net.Sockets.TcpClient -ArgumentList ([Net.Sockets.AddressFamily]::{af}); $c.Connect('{address}',{port}); $null=$c.GetStream().ReadByte(); $c.Close(); Write-Output 'CONNECTED'"
                            elif tool == 'python':
                                code = f"import socket;s=socket.socket({int(family)});s.connect(('{address}',{port}));s.recv(1);s.close();print('CONNECTED')"
                                command = "& '"+installed_python.replace("'", "''")+"' -B -c '"+code.replace("'", "''")+"'"
                            else:
                                code = f"const s=require('net').connect({{host:'{address}',port:{port}}});s.on('data',()=>{{s.end();console.log('CONNECTED')}})"
                                command = "& '"+str(node).replace("'", "''")+"' -e '"+code.replace("'", "''")+"'"
                            try:
                                self.turn(process, command, f'{family}-{tool}')
                            finally:
                                thread.join(21)
                            self.assertFalse(thread.is_alive())
                            self.assertFalse(errors, errors)
                            self.assertEqual(received, [True])
                            print(f'INSTALLED NETWORK {family.name} {tool}: PASS', flush=True)
            self.stop(process)

    InstalledBridge.engine = engine
    class InstalledAuth(WindowsAuth):
        def call(self, kind='login', seconds=3):
            operation(self.client, kind, seconds, Expired, root=self.root / 'state',
                      username='synthetic', password='SYNTHETIC_PASSWORD', executable=installed_python)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InstalledBridge)
    # Direct native timeout races use the bundled helper, never a copied system Python.
    for name in ('test_success_login_logout_no_persistence', 'test_timeout_late_server_result_cannot_install_token',
                 'test_logout_timeout_cannot_clear_new_state', 'test_repeated_timeout_has_no_worker_threads',
                 'test_timeout_releases_native_handles_and_excludes_argv_secrets'):
        suite.addTest(InstalledAuth(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    loaded = [Path(m.__file__).resolve() for name, m in sys.modules.items()
              if (name == 'jvcli' or name.startswith('jvcli.')) and getattr(m, '__file__', None)]
    if not loaded or not all(p.is_relative_to(app) for p in loaded):
        raise RuntimeError('Installed test loaded source-tree JV code')
    print(f'Installed module provenance: {len(loaded)} bundled modules; Python={sys.executable}', flush=True)
    if not result.wasSuccessful() or result.skipped:
        raise SystemExit(1)
    print(f'INSTALLED: {result.testsRun} tests, zero skips; six real tool network cases', flush=True)


def outer(installer, portable, node):
    import winreg
    sys.path.insert(0, str(ROOT / 'lib'))
    sys.path.insert(0, str(ROOT / 'tests'))
    from jvcli.platform import windows
    from windows_test_support import trusted_fixture_directory
    from build_windows import verify_payload, safe_name
    def user_path():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            try:
                return winreg.QueryValueEx(key, 'Path')[0]
            except FileNotFoundError:
                return ''
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\JV.CLI.Windows_is1'):
            raise RuntimeError('Existing user installation: refusing to replace it during acceptance')
    except FileNotFoundError:
        pass
    before_path = user_path()
    with tempfile.TemporaryDirectory(prefix='staging-package-', dir=ROOT) as temporary:
        root = Path(temporary)
        trusted_fixture_directory(root)
        app = root / 'application space \u0e44\u0e17\u0e22'
        workspace = root / 'workspace'; workspace.mkdir()
        state = windows.private_dir(root / 'user-state')
        marker = state / 'preserved.json'
        windows.atomic_write(marker, '{"synthetic":"preserved"}')
        env = windows.minimal_env()
        env.update(PROCESSOR_ARCHITECTURE='AMD64', USERPROFILE=str(Path.home()), JVCLI_HOME=str(state),
                   PYTHONHOME=str(root / 'absent'), PYTHONPATH=str(root / 'absent'))
        flags = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-']
        setup = [str(installer), *flags, f'/DIR={app}', '/TASKS=userpath']
        def command(args, expected=0, timeout=120):
            result = subprocess.run(list(map(str,args)), cwd=root, env=env, capture_output=True, timeout=timeout)
            if result.returncode != expected:
                raise AssertionError(f'Command {Path(str(args[0])).name} exited {result.returncode}, expected {expected}: {result.stderr.decode(errors="replace")}')
            return result
        unknown_created = False
        try:
            command(setup)
            print(f'INSTALL PASS; package files {verify_payload(app)}', flush=True)
            assert str(app) in user_path().split(';')
            assert command([app/'jvcli.exe','--version']).stdout.strip() == b'JV CLI ' + VERSION
            assert b'bridge' in command([app/'jvcli.exe','--help']).stdout
            doctor = json.loads(command([app/'jvcli.exe','doctor','--json']).stdout)
            assert doctor['ok'] and doctor['engine_version'] == '0.149.1'
            assert Path(doctor['install_root']) == app and Path(doctor['state_dir']) == state
            default_env = {k:v for k,v in env.items() if k != 'JVCLI_HOME'}
            default_env['LOCALAPPDATA'] = str(root/'synthetic-localappdata')
            default_result = subprocess.run([str(app/'jvcli.exe'),'doctor','--json'], env=default_env, cwd=root, capture_output=True, timeout=20)
            assert default_result.returncode == 0
            assert Path(json.loads(default_result.stdout)['state_dir']) == root/'synthetic-localappdata/JV/jv-cli'
            print('VERSION / HELP / DOCTOR / BUNDLED ENGINE / DEFAULT STATE / ISOLATED PATH: PASS', flush=True)
            # PATH convenience uses only the new application entry plus Windows paths.
            ps = Path(env['SYSTEMROOT']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            path_env = {**env, 'PATH': str(app)+os.pathsep+env['PATH']}
            found = subprocess.run([str(ps), '-NoProfile', '-Command', 'jvcli --version'],
                                   env=path_env, cwd=root, capture_output=True, timeout=10)
            assert found.returncode == 0 and found.stdout.strip() == b'JV CLI ' + VERSION
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            console = subprocess.run([str(app/'python/python.exe'), '-X', 'utf8', '-B',
                                      str(ROOT/'tests/fixtures/windows_package_console.py'),
                                      str(app/'jvcli.exe'), str(workspace)],
                                     env=env, cwd=root, capture_output=True, timeout=30,
                                     creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
            assert console.returncode == 0, console.stderr.decode(errors='replace')
            print(console.stdout.decode().strip(), flush=True)
            # Active application prevents both upgrade and uninstall, without killing it.
            active = subprocess.Popen([str(app/'jvcli.exe'),'bridge','--stdio','--execution-mode','trusted-host'],
                                      env=env, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                first = json.loads(active.stdout.readline())
                assert first['type'] == 'bridge.ready', first
                blocked = subprocess.run(setup, cwd=root, env=env, capture_output=True, timeout=30)
                assert blocked.returncode != 0 and active.poll() is None
                blocked = subprocess.run([str(app/'unins000.exe'),*flags], cwd=root, env=env, capture_output=True, timeout=30)
                assert blocked.returncode != 0 and active.poll() is None
                verify_payload(app)
            finally:
                active.communicate(b'{"type":"bridge.shutdown","request_id":"package"}\n',timeout=20)
            assert active.returncode == 0
            # A locked application file forces a mid-upgrade failure. Inno must
            # roll back preceding replacements and leave a runnable old package.
            from jvcli.platform import _windows_fs as fs
            fd = fs.open_public_read(app/'lib/jvcli/cli.py')
            try:
                failed = subprocess.run(setup, cwd=root, env=env, capture_output=True, timeout=90)
                assert failed.returncode != 0, 'Failed-upgrade fixture did not fail'
            finally:
                os.close(fd)
            verify_payload(app)
            assert command([app/'jvcli.exe','--version']).stdout.strip() == b'JV CLI ' + VERSION
            print('FAILED UPGRADE / ROLLBACK: PASS', flush=True)
            command(setup)
            verify_payload(app)
            assert marker.read_text() == '{"synthetic":"preserved"}'
            print('ACTIVE-USE REFUSAL / REINSTALL / STATE PRESERVATION: PASS', flush=True)
            import _winapi
            junction = app/'unsafe-junction'
            _winapi.CreateJunction(str(state), str(junction))
            try:
                assert subprocess.run(setup, cwd=root, env=env, capture_output=True, timeout=30).returncode != 0
                assert subprocess.run([str(app/'unins000.exe'),*flags], cwd=root, env=env, capture_output=True, timeout=30).returncode != 0
                assert marker.read_text() == '{"synthetic":"preserved"}'
            finally:
                junction.rmdir()
            print('INSTALL / UNINSTALL JUNCTION BOUNDARY: PASS', flush=True)
            # Test runner is source-only fixture code. Embedded Python + installed jvcli
            # are imported before any fixture paths; every JV module origin is checked.
            process = subprocess.run([str(app/'python/python.exe'), '-X', 'utf8', '-B', str(Path(__file__).resolve()),
                                      '--inner', str(app), '--node', str(node)], env=env, cwd=root, timeout=600)
            if process.returncode:
                raise RuntimeError('Installed runtime acceptance failed')
            # Portable artifact is independently extracted and verified with no install registration.
            extracted = root / 'portable'
            extracted.mkdir()
            with zipfile.ZipFile(portable) as archive:
                seen = set()
                for item in archive.infolist():
                    safe_name(item.filename)
                    assert item.filename.casefold() not in seen
                    seen.add(item.filename.casefold())
                    archive.extract(item, extracted)
            verify_payload(extracted)
            assert command([extracted/'jvcli.exe','--version']).stdout.strip() == b'JV CLI ' + VERSION
            print('PORTABLE EXTRACTION / VERSION / MANIFEST: PASS', flush=True)
            (app/'unknown-user-file.txt').write_text('PRESERVE')
            unknown_created = True
        finally:
            uninstaller = app / 'unins000.exe'
            if uninstaller.exists():
                command([uninstaller,*flags])
                for _ in range(300):
                    if not (app/'use.lock').exists():
                        break
                    time.sleep(.1)
            assert marker.read_text() == '{"synthetic":"preserved"}'
            assert not (app/'jvcli.exe').exists()
            if unknown_created:
                assert (app/'unknown-user-file.txt').read_text() == 'PRESERVE'
            assert user_path() == before_path, 'Uninstall changed unrelated user PATH'
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\JV.CLI.Windows_is1'):
                    raise AssertionError('Uninstall registration remains')
            except FileNotFoundError:
                pass
        print('UNINSTALL / PATH CLEANUP / STATE RETENTION: PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inner', type=Path)
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--portable', type=Path)
    parser.add_argument('--node', type=Path, required=True, help='Explicit test fixture only; not a runtime dependency')
    args = parser.parse_args()
    if not args.node.is_file():
        parser.error('The explicit Node test fixture does not exist')
    if args.inner:
        inner(args.inner.resolve(), args.node.resolve())
    elif args.installer and args.portable:
        outer(args.installer.resolve(), args.portable.resolve(), args.node.resolve())
    else:
        parser.error('--installer and --portable are required')
