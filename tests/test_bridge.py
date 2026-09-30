"""Offline bridge subprocess/transport tests; no installed CLI or real credentials."""
import contextlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli import bridge, cli
from jvcli.bridge_io import Emitter, MAX_LINE

PASSWORD = 'TEST_PASSWORD_DO_NOT_LEAK'
TOKEN = 'TEST_TOKEN_DO_NOT_LEAK'
KEY = 'TEST_ADAPTER_KEY_DO_NOT_LEAK'


class Peer:
    def __init__(self, root, *, public=False, state=None, workspace=None, structured=False):
        self.home = root / 'home'
        self.home.mkdir(exist_ok=True)
        self.workspace = workspace or root / 'workspace'
        self.workspace.mkdir(exist_ok=True)
        self.state = state or root / 'state'
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home),
               'JVCLI_HOME': str(self.state), 'PYTHONDONTWRITEBYTECODE': '1',
               'LANG': 'C.UTF-8', 'JVCLI_AGENT_API': '1' if structured else '0'}
        command = ([str(ROOT / 'bin/jvcli'), 'bridge', '--stdio'] if public else
                   [sys.executable, '-B', str(ROOT / 'tests/fixtures/bridge_runner.py')])
        self.p = subprocess.Popen(command, cwd=self.workspace, env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        self.pending = b''
        self.lines = []

    def send(self, typ, rid='r', **fields):
        self.raw(json.dumps({'type': typ, 'request_id': rid, **fields}, ensure_ascii=False).encode() + b'\n')

    def raw(self, data):
        self.p.stdin.write(data)
        self.p.stdin.flush()

    def read(self, timeout=8):
        end = time.monotonic() + timeout
        while b'\n' not in self.pending:
            left = end - time.monotonic()
            if left <= 0 or not select.select([self.p.stdout], [], [], left)[0]:
                raise AssertionError('Bridge frame timeout')
            data = os.read(self.p.stdout.fileno(), 65536)
            if not data:
                raise AssertionError('Bridge exited before expected frame')
            self.pending += data
        line, self.pending = self.pending.split(b'\n', 1)
        self.lines.append(line)
        result = json.loads(line)
        assert isinstance(result, dict)
        return result

    def until(self, typ):
        frames = []
        for _ in range(30):
            value = self.read()
            frames.append(value)
            if value['type'] == typ:
                return frames
        raise AssertionError('Expected event absent: ' + typ)

    def login(self, rid='login'):
        self.send('auth.login', rid, username='synthetic', base_url='http://127.0.0.1:9', password=PASSWORD)
        return self.read()

    def session(self, **fields):
        self.send('session.start', 'session', **fields)
        return self.read()

    def stop(self):
        if self.p.poll() is None:
            self.send('bridge.shutdown', 'shutdown')
            self.until('bridge.stopping')
        self.p.wait(timeout=18)
        rest = self.pending + self.p.stdout.read()
        for line in rest.splitlines():
            self.lines.append(line)
            assert isinstance(json.loads(line), dict)
        err = self.p.stderr.read()
        assert err == b'', err
        all_output = b'\n'.join(self.lines) + err
        for secret in (PASSWORD, TOKEN, KEY):
            assert secret.encode() not in all_output
        for pipe in (self.p.stdin, self.p.stdout, self.p.stderr):
            if not pipe.closed:
                pipe.close()
        return self.p.returncode

    def kill(self):
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait()
        for pipe in (self.p.stdin, self.p.stdout, self.p.stderr):
            if not pipe.closed:
                pipe.close()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def peer(self, **kwargs):
        p = Peer(self.root, **kwargs)
        self.addCleanup(p.kill)
        ready = p.read()
        self.assertEqual(ready['type'], 'bridge.ready')
        self.assertEqual(ready['protocol'], 1)
        self.assertEqual(ready['cli_version'], '0.4.8')
        self.assertEqual(ready['workspace'], str(p.workspace))
        return p

    def started(self):
        p = self.peer()
        self.assertEqual(p.login()['type'], 'auth.succeeded')
        session = p.session()
        self.assertEqual(session['type'], 'session.started')
        return p, session

    def test_public_startup_shutdown_never_creates_client_or_engine(self):
        p = self.peer(public=True)
        self.assertEqual(p.stop(), 0)
        self.assertFalse(p.state.exists())

    def test_public_idle_eof_is_clean(self):
        p = self.peer(public=True)
        p.p.stdin.close()
        p.p.wait(timeout=3)
        self.assertEqual(p.stop(), 0)

    def test_malformed_duplicate_nonobject_and_utf8_recover(self):
        p = self.peer(public=True)
        for raw in [b'{bad', b'{"type":"bridge.shutdown","request_id":"a","request_id":"b"}',
                    b'[]', b'null', b'\xff', b'{"type":"turn.start","request_id":"a","text":NaN}']:
            p.raw(raw + b'\n')
            self.assertEqual(p.read()['code'], 'invalid_request')
        self.assertEqual(p.stop(), 0)

    def test_unknown_fields_requests_ids_and_versions(self):
        p = self.peer(public=True)
        for typ, fields, code in [
            ('unknown', {}, 'invalid_request'),
            ('bridge.shutdown', {'protocol': 2}, 'unsupported_protocol'),
            ('bridge.shutdown', {'protocol': True}, 'unsupported_protocol'),
            *[('session.start', {key: 'forbidden'}, 'invalid_request') for key in
              ('workspace', 'executable', 'binary', 'shell', 'environment', 'PATH', 'HOME', 'CODEX_HOME', 'JVCLI_HOME', 'LD_PRELOAD', 'PYTHONPATH', 'image')],
        ]:
            p.send(typ, 'correlation', **fields)
            frame = p.read()
            self.assertEqual(frame['code'], code)
            self.assertEqual(frame['request_id'], 'correlation')
        for rid in ['', 'x' * 101, 'newline\nid', 3]:
            p.send('bridge.shutdown', rid)
            self.assertIsNone(p.read()['request_id'])
        self.assertEqual(p.stop(), 0)

    def test_oversized_input_discards_to_newline_then_recovers(self):
        p = self.peer(public=True)
        p.raw(b'x' * (MAX_LINE + 50) + b'\n')
        self.assertEqual(p.read()['code'], 'input_limit')
        self.assertEqual(p.stop(), 0)

    def test_auth_failure_is_sanitized_and_recoverable(self):
        p = self.peer()
        p.send('auth.login', password='wrong', username='synthetic', base_url='http://127.0.0.1:9')
        self.assertEqual(p.read()['code'], 'authentication_failed')
        self.assertEqual(p.login()['type'], 'auth.succeeded')
        self.assertEqual(p.stop(), 0)
        self.assertFalse((p.state / 'config.json').exists())

    def test_auth_replacement_logs_out_each_client_once(self):
        p = self.peer()
        p.login(); p.login('replacement')
        self.assertEqual(p.stop(), 0)
        lines = (p.state / 'fixture-lifecycle').read_text().splitlines()
        self.assertEqual(lines.count('login'), 2)
        self.assertEqual(lines.count('logout'), 2)

    def test_invalid_lifecycle_and_policy(self):
        p = self.peer()
        p.send('turn.start', text='synthetic')
        self.assertEqual(p.read()['code'], 'not_authenticated')
        p.login()
        p.send('turn.start', text='synthetic')
        self.assertEqual(p.read()['code'], 'session_not_started')
        for fields in ({'read_only': 1}, {'allow_network': 'yes'}, {'read_only': True, 'allow_network': True}):
            self.assertEqual(p.session(**fields)['code'], 'invalid_request')
        self.assertEqual(p.session(read_only=True)['network'], False)
        self.assertEqual(p.session()['code'], 'session_busy')
        self.assertEqual(p.login()['code'], 'session_busy')
        p.send('turn.cancel', turn_id='missing')
        self.assertEqual(p.read()['code'], 'cancel_error')
        self.assertEqual(p.stop(), 0)

    def test_multiple_turns_normalization_thai_and_secret_isolation(self):
        p, session = self.started()
        for i in range(2):
            p.send('turn.start', 't' + str(i), text='ช่วยตรวจ $(not shell)')
            frames = p.until('turn.completed')
            types = [f['type'] for f in frames]
            self.assertEqual(types, ['turn.started', 'command.started', 'command.completed',
                                    'tool.started', 'files.changed', 'assistant.message', 'turn.completed'])
            self.assertEqual(frames[-2]['text'], 'เรียบร้อยแล้ว')
            self.assertEqual(frames[-1]['request_id'], 't' + str(i))
            self.assertEqual(len({f['turn_id'] for f in frames}), 1)
        sid = session['session_id']
        run = p.state / 'runs' / sid
        capture = json.loads((run / 'fixture-capture.json').read_text())
        self.assertEqual(capture['stdin'], 'ช่วยตรวจ $(not shell)')
        self.assertNotIn(capture['stdin'], capture['argv'])
        self.assertIn('resume', capture['argv'])
        self.assertEqual(capture['env']['JVCLI_ADAPTER_KEY'], KEY)
        self.assertNotIn('JV_API_PASSWORD', capture['env'])
        self.assertNotIn(PASSWORD, json.dumps(capture))
        self.assertNotIn(TOKEN, json.dumps(capture))
        metadata = (run / 'session.json').read_text()
        for secret in (PASSWORD, TOKEN, KEY, capture['stdin']):
            self.assertNotIn(secret, metadata)
        self.assertFalse((p.state / 'config.json').exists())
        self.assertEqual(p.stop(), 0)
        lifecycle = (p.state / 'fixture-lifecycle').read_text().splitlines()
        self.assertEqual(lifecycle.count('runtime.close'), 1)
        self.assertEqual(lifecycle.count('logout'), 1)

    def test_resume_reuses_metadata_and_enforces_bindings(self):
        p, session = self.started()
        p.send('turn.start', text='success'); p.until('turn.completed'); p.stop()
        q = self.peer(state=p.state); q.login()
        resumed = q.session(resume_session_id=session['session_id'])
        self.assertEqual(resumed['thread_id'], 'thread_fixture')
        q.stop()
        q = self.peer(state=p.state, workspace=self.root / 'other-workspace'); q.login()
        self.assertEqual(q.session(resume_session_id=session['session_id'])['code'], 'invalid_session')
        q.stop()
        q = self.peer(state=p.state, structured=True); q.login()
        self.assertEqual(q.session(resume_session_id=session['session_id'])['code'], 'invalid_session')
        q.stop()

    def test_new_thread_and_session_lock(self):
        p, session = self.started()
        p.send('turn.start', text='success');p.until('turn.completed')
        p.send('thread.new');self.assertIsNone(p.read()['thread_id'])
        p.send('turn.start', text='success');p.until('turn.completed')
        capture = json.loads((p.state / 'runs' / session['session_id'] / 'fixture-capture.json').read_text())
        self.assertNotIn('resume', capture['argv'])
        q = self.peer(state=p.state);q.login()
        self.assertEqual(q.session(resume_session_id=session['session_id'])['code'], 'invalid_session')
        q.stop();p.stop()

    def test_failed_engine_variants_are_not_success(self):
        p, _ = self.started()
        for text in ('crash', 'malformed', 'oversized', 'failed'):
            p.send('turn.start', text=text)
            self.assertEqual(p.until('turn.failed')[-1]['code'], 'engine_error')
        p.stop()

    def test_busy_cancel_and_reuse_after_cleanup(self):
        p, _ = self.started()
        p.send('turn.start', 'slow', text='slow');turn = p.read()['turn_id']
        p.send('turn.start', 'busy', text='do not queue')
        self.assertEqual(p.read()['code'], 'turn_busy')
        p.send('thread.new');self.assertEqual(p.read()['code'], 'turn_busy')
        p.send('turn.cancel', 'cancel', turn_id=turn)
        frames = p.until('turn.cancelled')
        self.assertEqual(frames[0]['type'], 'turn.cancel.accepted')
        self.assertEqual(frames[-1]['remote_state'], 'unknown')
        self.assertTrue(frames[-1]['local'])
        p.send('turn.start', text='success');p.until('turn.completed');p.stop()

    def test_eof_cancels_owned_process_tree_and_logs_out(self):
        p, session = self.started()
        p.send('turn.start', text='tree');p.read()
        run = p.state / 'runs' / session['session_id']
        deadline = time.monotonic() + 5
        while not (run / 'fixture-child.pid').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        child = int((run / 'fixture-child.pid').read_text())
        leader = json.loads((run / 'fixture-capture.json').read_text())['pid']
        p.p.stdin.close();p.p.wait(timeout=15)
        self.assertEqual(p.stop(), 0)
        self.assertFalse(Path('/proc', str(leader)).exists())
        child_stat = Path('/proc', str(child), 'stat')
        self.assertTrue(not child_stat.exists() or child_stat.read_text().split()[2] == 'Z')
        self.assertEqual((p.state / 'fixture-lifecycle').read_text().splitlines().count('logout'), 1)

    def test_broken_stdout_stops_active_worker(self):
        p, _ = self.started()
        p.send('turn.start', text='slow');p.read()
        p.p.stdout.close();p.p.wait(timeout=15)
        self.assertEqual(p.p.returncode, 2)
        self.assertEqual((p.state / 'fixture-lifecycle').read_text().splitlines().count('logout'), 1)
        self.assertEqual(p.p.stderr.read(), b'')

    def test_output_backpressure_is_fatal_and_bounded(self):
        p, _ = self.started()
        p.send('turn.start', text='flood');p.read()
        # Deliberately stop draining stdout: bounded queue must cancel the turn.
        p.p.wait(timeout=15)
        self.assertEqual(p.p.returncode, 2)
        self.assertEqual((p.state / 'fixture-lifecycle').read_text().splitlines().count('logout'), 1)

    def test_workspace_root_rejected_before_auth(self):
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.root), 'JVCLI_HOME': str(self.root / 'state')}
        r = subprocess.run([str(ROOT / 'bin/jvcli'), 'bridge', '--stdio'], cwd='/', env=env,
                           input=b'', capture_output=True, timeout=5)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(json.loads(r.stdout)['code'], 'workspace_error')
        self.assertEqual(r.stderr, b'')

    def test_prompt_limit_and_strict_fields(self):
        p, _ = self.started()
        for text in ('', 'ก' * 35000):
            p.send('turn.start', text=text);self.assertEqual(p.read()['code'], 'invalid_request')
        p.send('turn.start', text='safe', image='/not/allowed')
        self.assertEqual(p.read()['code'], 'invalid_request');p.stop()

    def test_event_fields_are_bounded_and_unknown_types_ignored(self):
        self.assertIsNone(bridge.normalize({'type': 'unknown', 'secret': TOKEN}))
        frame = bridge.normalize({'type': 'item.completed', 'item': {
            'type': 'command_execution', 'command': 'x' * 9000,
            'aggregated_output': 'x' * 20000, 'exit_code': True}})
        self.assertEqual(len(frame['command']), 8192)
        self.assertEqual(len(frame['output']), 16384)
        self.assertIsNone(frame['exit_code'])

    def test_documented_transcript(self):
        p = self.peer()
        transcript = json.loads((ROOT / 'tests/fixtures/bridge_transcript.json').read_text())
        for step in transcript:
            p.raw(json.dumps(step['request'], ensure_ascii=False).encode() + b'\n')
            frames = [p.read() for _ in step['events']]
            self.assertEqual([f['type'] for f in frames], step['events'])
            self.assertEqual(frames[0]['request_id'], step['request']['request_id'])
        p.p.wait(timeout=15)
        self.assertEqual(p.stop(), 0)

    def test_shutdown_during_turn_cleans_up_once(self):
        p, _ = self.started()
        p.send('turn.start', 'active', text='slow')
        turn = p.read()
        p.send('bridge.shutdown', 'stop')
        frames = p.until('turn.cancelled')
        self.assertEqual(frames[0]['type'], 'bridge.stopping')
        self.assertEqual(frames[-1]['turn_id'], turn['turn_id'])
        self.assertEqual(frames[-1]['remote_state'], 'unknown')
        p.p.wait(timeout=15)
        self.assertEqual(p.stop(), 0)
        lifecycle = (p.state / 'fixture-lifecycle').read_text().splitlines()
        self.assertEqual(lifecycle.count('logout'), 1)
        self.assertEqual(lifecycle.count('runtime.close'), 1)
