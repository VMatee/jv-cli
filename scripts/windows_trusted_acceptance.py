"""Real pinned engine + public bridge; loopback synthetic JV service only."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import windows_preflight
from engine_smoke import run_structured_case
from windows_test_support import trusted_fixture_directory
from jvcli import cli
from jvcli.platform import windows
from jvcli.safety import read_private_json

ROOT = windows_preflight.ROOT
PASSWORD = 'SYNTHETIC_PASSWORD_NEVER_PERSIST'
TOKEN = 'SYNTHETIC_TOKEN_NEVER_PERSIST'


class TrustedAcceptance(unittest.TestCase):
    engine = None
    launcher = None
    tool_python = None

    def bridge_command(self):
        prefix = [str(self.launcher)] if self.launcher else [self.python, "-s", "-B", str(ROOT / "bin/jvcli")]
        return prefix + ["bridge", "--stdio", "--execution-mode", "trusted-host"]

    def bridge_env(self):
        env = windows.minimal_env()
        env.update(PROCESSOR_ARCHITECTURE="AMD64", USERPROFILE=str(Path.home()), JVCLI_HOME=str(self.state), JVCLI_POLL_INTERVAL="0.01",
                   JV_API_PASSWORD="PARENT_PASSWORD_SENTINEL", OPENAI_API_KEY="PARENT_OPENAI_SENTINEL")
        if not self.launcher:
            env.update(PYTHONHOME=sys.base_prefix, JVCLI_CODEX_BIN=self.engine)
        else:
            env.update(PYTHONHOME=str(self.root / "missing-python"), PYTHONPATH=str(self.root / "missing-modules"))
        return env

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='staging-trusted-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        trusted_fixture_directory(self.root)
        self.workspace = self.root / 'workspace \u0e44\u0e17\u0e22'
        self.workspace.mkdir()
        self.state = self.root / 'state'
        # Use a trusted executable directory even on permissive CI workspaces.
        for name in ('python.exe', f'python{sys.version_info.major}{sys.version_info.minor}.dll', 'python3.dll'):
            source = Path(sys.executable).parent / name
            if source.exists():
                shutil.copyfile(source, self.root / name)
        self.python = self.tool_python or str(self.root / 'python.exe')
        self.steps = queue.Queue()
        self.posts = 0
        self.jobs = {}
        self.errors = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, value=None):
                body = json.dumps(value).encode() if value is not None else b''
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                try:
                    if self.path == '/v1/auth/login':
                        assert json.loads(body)['password'] == PASSWORD
                        return self.reply(200, {'access_token': TOKEN})
                    assert self.headers.get('Authorization') == 'Bearer ' + TOKEN
                    if self.path == '/v1/auth/logout':
                        return self.reply(204)
                    assert self.path == '/v1/jobs'
                    answer = owner.steps.get_nowait()
                    owner.posts += 1
                    key = f'job_{owner.posts}'
                    job = {'id': key, 'conversation_id': 'conversation_synthetic', 'status': 'queued'}
                    owner.jobs[key] = {**job, 'status': 'succeeded', 'answer': json.dumps(answer), 'response': {'files': []}}
                    return self.reply(202, job)
                except Exception as exc:
                    owner.errors.append(type(exc).__name__)
                    self.reply(500, {})

            def do_GET(self):
                try:
                    assert self.headers.get('Authorization') == 'Bearer ' + TOKEN
                    self.reply(200, owner.jobs[self.path.rsplit('/', 1)[1]])
                except Exception as exc:
                    owner.errors.append(type(exc).__name__)
                    self.reply(500, {})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server_thread = threading.Thread(target=self.server.serve_forever)
        server_thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), server_thread.join()))
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def start(self, *, workspace=None):
        env = self.bridge_env()
        command = self.bridge_command()
        process = subprocess.Popen(command, cwd=workspace or self.workspace, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False)
        frames, diagnostics, transcript = queue.Queue(), [], []
        def read():
            for line in process.stdout:
                try:
                    frame = json.loads(line)
                except Exception:
                    frame = {'type': 'INVALID', 'line': repr(line)}
                transcript.append(frame)
                frames.put(frame)
        def read_errors():
            diagnostics.append(process.stderr.read())
        readers = [threading.Thread(target=read), threading.Thread(target=read_errors)]
        for thread in readers:
            thread.start()
        def cleanup():
            if process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)
            for thread in readers:
                thread.join(5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.addCleanup(cleanup)
        process.frames, process.diagnostics, process.transcript = frames, diagnostics, transcript
        ready = self.receive(process, 'bridge.ready')
        self.assertEqual(ready['protocol'], 1)
        return process

    def receive(self, process, expected, timeout=45):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                frame = process.frames.get(timeout=.1)
            except queue.Empty:
                if process.poll() is not None:
                    self.fail(f'Bridge exited {process.returncode}; stderr={process.diagnostics}')
                continue
            if frame['type'] == expected:
                return frame
            self.assertNotIn(frame['type'], ('INVALID', 'request.error', 'turn.failed'), frame)
        self.fail(f'Timed out awaiting {expected}; frames={process.transcript}; stderr={process.diagnostics}')

    def send(self, process, typ, rid='request', **fields):
        process.stdin.write((json.dumps({'type': typ, 'request_id': rid, **fields}, ensure_ascii=False) + '\n').encode())
        process.stdin.flush()

    def login(self, process):
        self.send(process, 'auth.login', 'login', username='synthetic', base_url=self.base, password=PASSWORD)
        self.assertEqual(self.receive(process, 'auth.succeeded')['request_id'], 'login')

    def session(self, process, **options):
        self.send(process, 'session.start', 'session', **options)
        frame = self.receive(process, 'session.started')
        self.assertEqual(frame['sandbox'], 'danger-full-access')
        self.assertIs(frame['network'], True)
        return frame['session_id']

    def stop(self, process):
        self.send(process, 'bridge.shutdown', 'stop')
        self.receive(process, 'bridge.stopping')
        self.assertEqual(process.wait(20), 0)
        self.assertFalse(self.errors, self.errors)

    def turn(self, process, command, rid='turn'):
        self.steps.put({'type': 'tool_call', 'name': 'shell_command', 'arguments': {'command': command}})
        self.steps.put({'type': 'final', 'text': 'SYNTHETIC_DONE'})
        self.send(process, 'turn.start', rid, text='Synthetic Unicode \u0e44\u0e17\u0e22 task; stdin only')
        self.assertEqual(self.receive(process, 'turn.started')['request_id'], rid)
        self.assertEqual(self.receive(process, 'turn.completed')['request_id'], rid)

    def test_public_two_turns_resume_full_access_and_secrets(self):
        process = self.start()
        self.login(process)
        sid = self.session(process)
        outside = self.root / 'outside.txt'
        command = f"Set-Content -LiteralPath '{outside}' -Value 'OUTSIDE_OK'; Set-Content -LiteralPath 'inside.txt' -Value 'INSIDE_OK'"
        self.turn(process, command)
        self.assertIn('OUTSIDE_OK', outside.read_text())
        self.assertIn('INSIDE_OK', (self.workspace / 'inside.txt').read_text())
        self.turn(process, "if ($env:JVCLI_ADAPTER_KEY -or $env:JV_API_PASSWORD -or $env:OPENAI_API_KEY) { Write-Output 'SECRET_LEAK' } else { Write-Output 'TOOL_ISOLATED' }", 'second')
        self.stop(process)
        transcript = json.dumps(process.transcript)
        tool_output = ''.join(f.get('output', '') for f in process.transcript)
        self.assertIn('TOOL_ISOLATED', tool_output)
        self.assertNotIn('SECRET_LEAK', tool_output)
        self.assertTrue(all(f['exit_code'] == 0 for f in process.transcript if f['type'] == 'command.completed'))
        self.assertEqual(sum(f['type'] == 'bridge.ready' for f in process.transcript), 1)
        metadata = read_private_json(self.state / 'runs' / sid / 'session.json')
        self.assertEqual(metadata['execution_mode'], 'trusted-host')
        self.assertEqual(metadata['last_exit_code'], 0)
        config = (self.state / 'runs' / sid / 'engine-config.toml').read_text()
        self.assertIn('sandbox_mode = "danger-full-access"', config)
        self.assertIn('approval_policy = "never"', config)
        process2 = self.start()
        self.login(process2)
        self.assertEqual(self.session(process2, resume_session_id=sid), sid)
        self.turn(process2, "Write-Output 'RESUME_OK'", 'resumed')
        self.stop(process2)
        self.assertIn('RESUME_OK', ''.join(f.get('output', '') for f in process2.transcript))
        for process in (process, process2):
            for _ in range(50):
                if process.diagnostics:
                    break
                time.sleep(.01)
            self.assertIn(b'Execution mode: trusted-host', b''.join(process.diagnostics))
            for secret in (PASSWORD, TOKEN, 'PARENT_PASSWORD_SENTINEL', 'PARENT_OPENAI_SENTINEL'):
                self.assertNotIn(secret, json.dumps(process.transcript) + str(process.diagnostics))
        for path in self.state.rglob('*'):
            if path.is_file():
                data = path.read_bytes()
                for secret in (PASSWORD, TOKEN, 'PARENT_PASSWORD_SENTINEL', 'PARENT_OPENAI_SENTINEL'):
                    self.assertNotIn(secret.encode(), data, str(path))

    def test_restrictions_rejected_before_session_or_engine(self):
        process = self.start()
        self.login(process)
        for fields in ({'allow_network': False}, {'read_only': True}):
            self.send(process, 'session.start', **fields)
            self.assertEqual(self.receive(process, 'request.error')['code'], 'unsupported_capability')
        self.assertEqual(self.posts, 0)
        self.stop(process)

    def test_eof_final_frame_errors_and_protocol_only(self):
        process = self.start()
        process.stdin.write(b'{bad}\n{"type":"unknown","request_id":"u"}\n')
        process.stdin.flush()
        for _ in range(2):
            self.assertEqual(self.receive(process, 'request.error')['code'], 'invalid_request')
        process.stdin.write(b'{"type":"bridge.shutdown","request_id":"final"}')
        process.stdin.close()
        self.receive(process, 'bridge.stopping')
        self.assertEqual(process.wait(10), 0)
        other = self.start()
        other.stdin.close()
        self.assertEqual(other.wait(10), 0)

    def test_broken_output_cleanup(self):
        # Stop the local reader by closing the OS read handle, not killing JV.
        process = subprocess.Popen(self.bridge_command(), cwd=self.workspace, env=self.bridge_env(),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(json.loads(process.stdout.readline())['type'], 'bridge.ready')
            process.stdout.close()
            process.stdout = None
            self.assertEqual(process.wait(10), 2)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def test_conflicting_owner_corrupt_metadata_and_workspace_binding(self):
        first = self.start()
        self.login(first)
        sid = self.session(first)
        second = self.start()
        self.login(second)
        self.send(second, 'session.start', resume_session_id=sid)
        self.assertEqual(self.receive(second, 'request.error')['code'], 'invalid_session')
        self.stop(second)
        self.stop(first)
        alternate = self.root / 'other-workspace'
        alternate.mkdir()
        third = self.start(workspace=alternate)
        self.login(third)
        self.send(third, 'session.start', resume_session_id=sid)
        self.assertEqual(self.receive(third, 'request.error')['code'], 'invalid_session')
        self.stop(third)
        windows.atomic_write(self.state / 'runs' / sid / 'session.json', '{broken')
        fourth = self.start()
        self.login(fourth)
        self.send(fourth, 'session.start', resume_session_id=sid)
        self.assertEqual(self.receive(fourth, 'request.error')['code'], 'invalid_session')
        self.stop(fourth)

    def test_cancellation_owned_tree_and_unrelated_survival(self):
        self.owned_tree_end('cancel')

    def test_shutdown_owned_tree_and_unrelated_survival(self):
        self.owned_tree_end('shutdown')

    def test_eof_owned_tree_and_unrelated_survival(self):
        self.owned_tree_end('eof')

    def test_parent_death_owned_tree_and_unrelated_survival(self):
        self.owned_tree_end('death')

    def owned_tree_end(self, ending):
        sentinel = subprocess.Popen([self.python, '-B', '-c', 'import time; time.sleep(120)'],
                                    env={**windows.minimal_env(), 'PYTHONHOME': sys.base_prefix})
        self.addCleanup(lambda: (sentinel.terminate(), sentinel.wait(5)))
        marker = self.workspace / 'owned.json'
        script = self.workspace / 'tree.py'
        script.write_text('import os,sys,subprocess,time,json\nfrom pathlib import Path\n'
                          "p=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(120)'])\n"
                          f'm=Path({str(marker)!r});t=m.with_suffix(".tmp");t.write_text(json.dumps([os.getpid(),p.pid]));os.replace(t,m)\n'
                          'time.sleep(120)\n', encoding='utf-8')
        process = self.start()
        self.login(process)
        self.session(process)
        self.steps.put({'type': 'tool_call', 'name': 'shell_command', 'arguments': {
            'command': f"& '{self.tool_python or sys.executable}' -B '{script}'", 'timeout_ms': 120000}})
        self.send(process, 'turn.start', text='SYNTHETIC_CANCEL_STDIN')
        started = self.receive(process, 'turn.started')
        for _ in range(400):
            if marker.exists():
                break
            time.sleep(.05)
        self.assertTrue(marker.exists(), process.transcript)
        pids = json.loads(marker.read_text())
        from jvcli.platform import _windows_fs as fs
        open_process = fs._api(fs.K, 'OpenProcess', fs.W.HANDLE, fs.D, fs.W.BOOL, fs.D)
        wait = fs._api(fs.K, 'WaitForSingleObject', fs.D, fs.W.HANDLE, fs.D)
        handles = [fs._check(open_process(0x100000, False, pid)) for pid in pids]
        try:
            for handle in handles:
                self.assertEqual(wait(handle, 0), 258)
            self.send(process, 'turn.start', 'busy', text='MUST_NOT_SUBMIT')
            self.assertEqual(self.receive(process, 'request.error')['code'], 'turn_busy')
            if ending == 'cancel':
                self.send(process, 'turn.cancel', 'cancel', turn_id=started['turn_id'])
                self.assertEqual(self.receive(process, 'turn.cancel.accepted')['remote_state'], 'unknown')
                self.assertTrue(self.receive(process, 'turn.cancelled')['local'])
            elif ending == 'shutdown':
                self.stop(process)
            elif ending == 'eof':
                process.stdin.close()
                self.assertEqual(process.wait(20), 0)
            else:
                process.kill()
                process.wait(10)
            for handle in handles:
                self.assertEqual(wait(handle, 5000), 0)
            self.assertIsNone(sentinel.poll())
            self.assertEqual(self.posts, 1)
            if ending == 'cancel':
                self.stop(process)
        finally:
            for handle in handles:
                fs._close(handle)

    def test_public_backpressure_is_fatal(self):
        process = subprocess.Popen(self.bridge_command(), cwd=self.workspace, env=self.bridge_env(),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def flood():
            try:
                process.stdin.write(b'{invalid}\n' * 100000)
                process.stdin.flush()
            except (OSError, ValueError):
                pass
        thread = threading.Thread(target=flood)
        thread.start()
        try:
            self.assertEqual(process.wait(15), 2)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(5)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            process.communicate(timeout=5)

    def test_real_structured_journal(self):
        state = windows.private_dir(self.root / 'structured-case')
        old = Path.cwd()
        os.chdir(self.workspace)
        try:
            run_structured_case(self.engine, state, "Write-Output 'STRUCTURED_NATIVE_OK'",
                                'STRUCTURED_NATIVE_OK', execution_mode='trusted-host')
            data = read_private_json(state / 'structured/state.json')
            self.assertEqual([item['phase'] for item in data['rounds']], ['continued', 'final'])
        finally:
            os.chdir(old)


def run(engine):
    TrustedAcceptance.engine = windows.find_engine(ROOT / 'runtime', engine)
    if cli._version_of_engine(TrustedAcceptance.engine) != '0.149.1':
        raise RuntimeError('Wrong pinned engine')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TrustedAcceptance))
    return result.wasSuccessful() and not result.skipped


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True)
    raise SystemExit(0 if run(parser.parse_args().engine) else 1)
