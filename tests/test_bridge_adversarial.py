"""Adversarial protocol/lifecycle checks with synthetic dependencies only."""
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import unittest

from test_bridge import Peer, ROOT


class AdversarialBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def peer(self, **kwargs):
        p = Peer(self.root, **kwargs)
        self.addCleanup(p.kill)
        self.assertEqual(p.read()['type'], 'bridge.ready')
        return p

    def started(self):
        p = self.peer()
        self.assertEqual(p.login()['type'], 'auth.succeeded')
        session = p.session()
        self.assertEqual(session['type'], 'session.started')
        return p, session

    def test_sigterm_active_engine_cleans_up(self):
        p, session = self.started()
        p.send('turn.start', text='slow')
        p.read()
        capture = p.state / 'runs' / session['session_id'] / 'fixture-capture.json'
        deadline = time.monotonic() + 3
        while not capture.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        pid = json.loads(capture.read_text())['pid']
        def cleanup():
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.addCleanup(cleanup)
        p.p.send_signal(signal.SIGTERM)
        p.p.wait(timeout=8)
        self.assertEqual(p.p.returncode, 2)
        self.assertFalse(Path('/proc', str(pid)).exists())
        lifecycle = (p.state / 'fixture-lifecycle').read_text().splitlines()
        self.assertEqual(lifecycle.count('logout'), 1)
        self.assertEqual(lifecycle.count('runtime.close'), 1)
        self.assertEqual(p.stop(), 2)

    def test_partial_input_does_not_starve_turn_completion(self):
        p, _ = self.started()
        p.send('turn.start', text='success')
        self.assertEqual(p.read()['type'], 'turn.started')
        p.raw(b'{"type":')
        stop = threading.Event()
        def feed():
            while not stop.wait(.01):
                p.raw(b' ')
        thread = threading.Thread(target=feed)
        thread.start()
        try:
            types = []
            for _ in range(10):
                frame = p.read(timeout=1)
                types.append(frame['type'])
                if frame['type'] == 'turn.completed':
                    break
            self.assertIn('turn.completed', types)
        finally:
            stop.set()
            thread.join(1)
            p.raw(b'"unknown","request_id":"partial"}\n')
        p.until('request.error')
        self.assertEqual(p.stop(), 0)

    def test_slow_authentication_has_overall_deadline(self):
        p = self.peer()
        p.send('auth.login', username='slow-auth', base_url='http://127.0.0.1:9',
               password='TEST_PASSWORD_DO_NOT_LEAK')
        self.assertEqual(p.read(timeout=1)['code'], 'authentication_failed')
        self.assertEqual(p.login()['type'], 'auth.succeeded')
        self.assertEqual(p.stop(), 0)

    def test_protocol_versions_and_hostile_ids(self):
        p = self.peer(public=True)
        for version in (2, True, 1.0, '1', None):
            p.send('thread.new', protocol=version)
            self.assertEqual(p.read()['code'], 'unsupported_protocol')
        for rid in (None, '', 'ไทย', 'a\x00b', {}, 'x' * 101):
            p.send('thread.new', rid)
            self.assertIsNone(p.read()['request_id'])
        for version in (None, 1):
            fields = {} if version is None else {'protocol': version}
            p.send('thread.new', 'reuse', **fields)
            self.assertEqual(p.read()['code'], 'not_authenticated')
        self.assertEqual(p.stop(), 0)

    def test_hostile_json_recovers_and_final_line_without_newline(self):
        p = self.peer(public=True)
        invalid = [b'42', b'"text"', b'Infinity', b'-Infinity', b'NaN',
                   b'[' * 2000 + b']' * 2000, b'{"a":{"x":1,"x":2}}',
                   b'{"type":"auth.login","request_id":"x","username":"\\ud800","base_url":"http://localhost","password":"fake"}']
        for raw in invalid:
            p.raw(raw + b'\n')
            self.assertEqual(p.read()['code'], 'invalid_request')
        p.raw(b'\n \t\n{"type":"thread.new","request_id":"a"}\n{"type":"thread.new","request_id":"b"}\n')
        self.assertEqual([p.read()['request_id'], p.read()['request_id']], ['a', 'b'])
        p.raw(b'{"type":"bridge.shutdown","request_id":"last"}')
        p.p.stdin.close()
        self.assertEqual(p.read()['type'], 'bridge.stopping')
        p.p.wait(timeout=5)
        self.assertEqual(p.stop(), 0)

    def test_fragmented_unicode_message(self):
        p = self.peer(public=True)
        raw = json.dumps({'type': 'turn.start', 'request_id': 'thai', 'text': 'สวัสดี'}, ensure_ascii=False).encode() + b'\n'
        for byte in raw:
            p.raw(bytes([byte]))
        frame = p.read()
        self.assertEqual(frame['code'], 'not_authenticated')
        self.assertEqual(frame['request_id'], 'thai')
        self.assertEqual(p.stop(), 0)

    def test_unknown_authority_fields_rejected(self):
        p = self.peer(public=True)
        for field in ('cwd', 'directory', 'path_to_project', 'engine_path', 'args',
                      'env', 'sandbox', 'yolo', 'system_write', 'unrestricted_network'):
            p.send('session.start', **{field: 'forbidden'})
            self.assertEqual(p.read()['code'], 'invalid_request')
        self.assertEqual(p.stop(), 0)

    def test_state_matrix_and_duplicate_correlation_labels(self):
        p = self.peer()
        requests = [('session.start', {}), ('turn.start', {'text': 'success'}),
                    ('turn.cancel', {'turn_id': 'missing'}), ('thread.new', {})]
        for typ, fields in requests:
            p.send(typ, 'same', **fields)
            self.assertEqual(p.read()['code'], 'not_authenticated')
        p.login()
        for typ, fields in requests[1:]:
            p.send(typ, 'same', **fields)
            self.assertEqual(p.read()['code'], 'session_not_started')
        self.assertEqual(p.session()['network'], True)
        p.send('turn.start', 'same', text='slow')
        turn = p.read()
        for typ, fields, expected in [
            ('auth.login', {'username': 'synthetic', 'password': 'TEST_PASSWORD_DO_NOT_LEAK', 'base_url': 'http://127.0.0.1:9'}, 'session_busy'),
            ('session.start', {}, 'session_busy'), ('turn.start', {'text': 'success'}, 'turn_busy'),
            ('thread.new', {}, 'turn_busy'), ('turn.cancel', {'turn_id': 'wrong'}, 'cancel_error')]:
            p.send(typ, 'same', **fields)
            frame = p.read()
            self.assertEqual((frame['code'], frame['request_id']), (expected, 'same'))
        p.send('turn.cancel', 'same', turn_id=turn['turn_id'])
        self.assertEqual(p.read()['type'], 'turn.cancel.accepted')
        self.assertEqual(p.until('turn.cancelled')[-1]['request_id'], 'same')
        p.send('turn.start', 'same', text='success')
        frames = p.until('turn.completed')
        self.assertNotEqual(frames[0]['turn_id'], turn['turn_id'])
        self.assertEqual(p.stop(), 0)

    def test_requests_after_shutdown_are_not_processed(self):
        p = self.peer()
        p.raw(b'{"type":"bridge.shutdown","request_id":"bye"}\n'
              b'{"type":"auth.login","request_id":"late","username":"synthetic","password":"TEST_PASSWORD_DO_NOT_LEAK","base_url":"http://127.0.0.1:9"}\n')
        self.assertEqual(p.read()['type'], 'bridge.stopping')
        p.p.wait(timeout=5)
        self.assertEqual(p.stop(), 0)
        self.assertFalse(p.state.exists())

    def test_cleanup_busy_and_repeated_cancel(self):
        p = self.peer(fixture='cleanup-slow')
        p.login(); p.session()
        p.send('turn.start', 'original', text='synthetic')
        turn = p.read()
        for rid in ('cancel1', 'cancel2'):
            p.send('turn.cancel', rid, turn_id=turn['turn_id'])
            self.assertEqual(p.read()['type'], 'turn.cancel.accepted')
        p.send('turn.start', text='must not start')
        self.assertEqual(p.read()['code'], 'turn_busy')
        p.send('thread.new')
        self.assertEqual(p.read()['code'], 'turn_busy')
        terminal = p.until('turn.cancelled')[-1]
        self.assertEqual((terminal['local'], terminal['remote_state']), (True, 'unknown'))
        self.assertEqual(p.stop(), 0)

    def test_immediate_cancel_and_shutdown_have_one_terminal(self):
        p, _ = self.started()
        for i in range(6):
            p.send('turn.start', str(i), text='success')
            turn = p.read()
            p.send('turn.cancel', 'cancel', turn_id=turn['turn_id'])
            seen, acknowledged = [], False
            while not seen or not acknowledged:
                frame = p.read()
                if frame['type'] in ('turn.completed', 'turn.failed', 'turn.cancelled'):
                    seen.append(frame['type'])
                if frame['type'] in ('turn.cancel.accepted', 'request.error'):
                    acknowledged = True
            self.assertEqual(len(seen), 1)
        p.send('turn.start', 'shutdown-race', text='success')
        turn = p.read()
        p.send('turn.cancel', 'cancel', turn_id=turn['turn_id'])
        p.send('bridge.shutdown', 'bye')
        p.until('bridge.stopping')
        p.p.wait(timeout=8)
        self.assertEqual(p.stop(), 0)
        finals = [json.loads(line) for line in p.lines if json.loads(line)['type'] in ('turn.completed', 'turn.failed', 'turn.cancelled')]
        self.assertEqual(sum(f['turn_id'] == turn['turn_id'] for f in finals), 1)

    def test_failure_cleanup_and_recoverable_worker_exception(self):
        for mode in ('engine-missing', 'session-failure', 'context-failure', 'logout-failure', 'worker-error'):
            with self.subTest(mode=mode):
                root = self.root / mode; root.mkdir()
                p = Peer(root, fixture=mode); self.addCleanup(p.kill)
                p.read(); p.login()
                session = p.session()
                if mode in ('engine-missing', 'session-failure'):
                    self.assertEqual(session['code'], 'invalid_session')
                else:
                    self.assertEqual(session['type'], 'session.started')
                if mode == 'worker-error':
                    for _ in range(2):
                        p.send('turn.start', text='synthetic')
                        self.assertEqual(p.until('turn.failed')[-1]['code'], 'engine_error')
                self.assertEqual(p.stop(), 2 if mode == 'context-failure' else 0)
                lifecycle = (p.state / 'fixture-lifecycle').read_text().splitlines()
                self.assertEqual(lifecycle.count('logout'), 1)
                self.assertLessEqual(lifecycle.count('runtime.close'), 1)

    def test_hung_worker_is_fatal_without_concurrent_teardown(self):
        p = self.peer(fixture='worker-hang')
        p.login(); p.session()
        p.send('turn.start', text='synthetic')
        p.read()
        self.assertEqual(p.stop(), 2)
        lifecycle = (p.state / 'fixture-lifecycle').read_text().splitlines()
        self.assertNotIn('runtime.close', lifecycle)
        self.assertNotIn('logout', lifecycle)

    def test_sigint_idle_cleans_up_without_traceback(self):
        p = self.peer()
        p.login(); p.session()
        p.p.send_signal(signal.SIGINT)
        p.p.wait(timeout=8)
        self.assertEqual(p.stop(), 2)
        lifecycle = (p.state / 'fixture-lifecycle').read_text().splitlines()
        self.assertEqual(lifecycle.count('logout'), 1)
        self.assertEqual(lifecycle.count('runtime.close'), 1)

    def test_hostile_prompt_stays_on_stdin(self):
        p, session = self.started()
        text = '$(touch SHOULD_NOT_EXIST)\n`id`\n"; rm -rf ...\nช่วยตรวจโปรเจกต์นี้\n'
        p.send('turn.start', text=text)
        p.until('turn.completed')
        run = p.state / 'runs' / session['session_id']
        capture = json.loads((run / 'fixture-capture.json').read_text())
        self.assertEqual(capture['stdin_raw'], text + '\n')
        self.assertNotIn(text, json.dumps(capture['argv']))
        self.assertNotIn(text, (run / 'session.json').read_text())
        self.assertFalse((p.workspace / 'SHOULD_NOT_EXIST').exists())
        self.assertEqual(p.stop(), 0)

    def test_resume_account_corruption_and_permission_policy(self):
        p, session = self.started(); p.stop()
        path = p.state / 'runs' / session['session_id'] / 'session.json'
        original = path.read_text()
        for change in ({'username': 'other'}, {'base_url': 'http://localhost:9'}, {'transport_mode': 'structured'}, None):
            if change is None:
                path.write_text('{invalid')
            else:
                path.write_text(json.dumps({**json.loads(original), **change}))
            q = self.peer(state=p.state); q.login()
            self.assertEqual(q.session(resume_session_id=session['session_id'])['code'], 'invalid_session')
            self.assertEqual(q.stop(), 0)
        path.write_text(original)
        q = self.peer(state=p.state); q.login()
        result = q.session(resume_session_id=session['session_id'], read_only=True)
        self.assertEqual((result['sandbox'], result['network']), ('read-only', False))
        self.assertEqual(q.stop(), 0)

    def test_parser_flags_fail_before_protocol(self):
        import subprocess
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.root), 'JVCLI_HOME': str(self.root / 'state')}
        for args in (['bridge'], *[[flag, 'bridge', '--stdio'] for flag in ('--read-only', '--allow-network', '--no-network', '--verbose')]):
            result = subprocess.run([str(ROOT / 'bin/jvcli'), *args], env=env, cwd=self.root,
                                    input=b'', capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b'')
        result = subprocess.run([str(ROOT / 'bin/jvcli'), 'bridge', '--help'], env=env, cwd=self.root, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'machine protocol', result.stdout)

    def test_normalization_allowlist_paths_and_limits(self):
        from jvcli.bridge import normalize
        paths = ['../../etc/passwd', '/tmp/example', 'C:\\Windows\\file', 'line\nbreak', '\x1b[31mred\x1b[0m', 'ไฟล์ไทย.txt']
        frame = normalize({'type': 'item.completed', 'item': {'type': 'file_changes',
                          'changes': [{'path': x, 'kind': 'unknown', 'secret': 'hidden'} for x in paths], 'secret': 'hidden'}})
        self.assertEqual(set(frame), {'type', 'changes'})
        self.assertEqual(frame['changes'][0]['path'], '../../etc/passwd')
        self.assertEqual(frame['changes'][-1]['path'], 'ไฟล์ไทย.txt')
        self.assertNotIn('\x1b', json.dumps(frame, ensure_ascii=False))
        self.assertNotIn('hidden', json.dumps(frame))
        frame = normalize({'type': 'item.completed', 'item': {'type': 'file_change', 'changes': [{'path': 'ก' * 1000, 'kind': {}}] * 100}})
        self.assertEqual(len(frame['changes']), 50)
        self.assertTrue(all(len(x['path'].encode()) <= 1024 for x in frame['changes']))
        for kind in ('mcp_tool_call', 'web_search'):
            self.assertEqual(set(normalize({'type': 'item.started', 'item': {'type': kind, 'tool': 'safe', 'arguments': 'hidden'}})), {'type', 'name'})
        for code in (True, '1', {}, 2 ** 40):
            frame = normalize({'type': 'item.completed', 'item': {'type': 'command_execution', 'exit_code': code}})
            self.assertIsNone(frame['exit_code'])

    def test_resume_rejects_non_identifier_thread_metadata(self):
        p, session = self.started(); p.stop()
        path = p.state / 'runs' / session['session_id'] / 'session.json'
        metadata = json.loads(path.read_text())
        for invalid in ({'unexpected': 'private metadata'}, 123, 'bad\nthread', 'x' * 101):
            path.write_text(json.dumps({**metadata, 'thread_id': invalid}))
            q = self.peer(state=p.state); q.login()
            response = q.session(resume_session_id=session['session_id'])
            self.assertEqual(response.get('code'), 'invalid_session')
            self.assertNotIn('private metadata', json.dumps(response))
            q.stop()

    def test_workspace_checks_and_symlink_resolution(self):
        import subprocess
        home = self.root / 'home'; home.mkdir()
        workspace = self.root / 'project'; workspace.mkdir()
        env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'JVCLI_HOME': str(self.root / 'state')}
        for cwd in (home, ROOT, Path('/')):
            result = subprocess.run([str(ROOT / 'bin/jvcli'), 'bridge', '--stdio'], env=env, cwd=cwd, input=b'', capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['code'], 'workspace_error')
        config = workspace / '.codex'; config.mkdir()
        (config / 'config.toml').write_text('# synthetic forbidden project config\n')
        result = subprocess.run([str(ROOT / 'bin/jvcli'), 'bridge', '--stdio'], env=env, cwd=workspace, input=b'', capture_output=True, timeout=5)
        self.assertEqual(json.loads(result.stdout)['code'], 'workspace_error')
        clean = self.root / 'clean'; clean.mkdir()
        link = self.root / 'link'; link.symlink_to(clean, target_is_directory=True)
        result = subprocess.run([str(ROOT / 'bin/jvcli'), 'bridge', '--stdio'], env=env, cwd=link,
                                input=b'{"type":"bridge.shutdown","request_id":"bye"}\n', capture_output=True, timeout=5)
        self.assertEqual(json.loads(result.stdout.splitlines()[0])['workspace'], str(clean))
        self.assertEqual(result.returncode, 0)

    def test_sessions_command_reads_bridge_metadata_offline(self):
        import subprocess
        p, session = self.started(); p.stop()
        env = {'PATH': os.environ['PATH'], 'HOME': str(p.home), 'JVCLI_HOME': str(p.state)}
        result = subprocess.run([str(ROOT / 'bin/jvcli'), 'sessions'], env=env, cwd=p.workspace, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn(session['session_id'].encode(), result.stdout)
        for secret in (b'TEST_PASSWORD_DO_NOT_LEAK', b'TEST_TOKEN_DO_NOT_LEAK', b'TEST_ADAPTER_KEY_DO_NOT_LEAK'):
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_signal_during_synchronous_auth_exits_after_deadline(self):
        p = self.peer()
        p.send('auth.login', username='slow-auth', password='TEST_PASSWORD_DO_NOT_LEAK', base_url='http://127.0.0.1:9')
        time.sleep(.05)
        p.p.send_signal(signal.SIGTERM)
        p.p.wait(timeout=3)
        self.assertEqual(p.stop(), 2)
        self.assertEqual((p.state / 'fixture-lifecycle').read_text().splitlines().count('logout'), 1)

    def test_oversized_outgoing_frame_fails_without_partial_frame(self):
        from jvcli.bridge_io import Emitter, MAX_EVENT
        r, w = os.pipe()
        emitter = Emitter(w)
        try:
            with self.assertRaises(BrokenPipeError):
                emitter.emit({'type': 'assistant.message', 'text': 'x' * MAX_EVENT})
            self.assertTrue(emitter.failed.is_set())
        finally:
            emitter.close()
            os.close(w)
        self.assertEqual(os.read(r, MAX_EVENT), b'')
        os.close(r)

    def test_resume_thread_cannot_be_an_engine_option(self):
        p, session = self.started(); p.stop()
        path = p.state / 'runs' / session['session_id'] / 'session.json'
        metadata = json.loads(path.read_text())
        path.write_text(json.dumps({**metadata, 'thread_id': '--dangerously-bypass-approvals-and-sandbox'}))
        q = self.peer(state=p.state); q.login()
        self.assertEqual(q.session(resume_session_id=session['session_id']).get('code'), 'invalid_session')
        self.assertEqual(q.stop(), 0)

    def test_engine_thread_event_cannot_inject_resume_option(self):
        p, session = self.started()
        p.send('turn.start', text='option-thread')
        self.assertEqual(p.until('turn.failed')[-1]['code'], 'engine_error')
        run = p.state / 'runs' / session['session_id']
        self.assertIsNone(json.loads((run / 'session.json').read_text())['thread_id'])
        p.send('turn.start', text='success')
        p.until('turn.completed')
        capture = json.loads((run / 'fixture-capture.json').read_text())
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', capture['argv'])
        self.assertNotIn('resume', capture['argv'])
        self.assertEqual(p.stop(), 0)
