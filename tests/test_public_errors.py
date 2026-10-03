"""Synthetic remote failures through transport, adapter HTTP, session and bridge."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.agent import AgentProcessor
from jvcli.bridge import Bridge
from jvcli.safety import JvError, RemoteInferenceError, public_remote_error
from jvcli.structured import StructuredProcessor
from jvcli.transport import JvApiClient, JvClientConfig

AUTH = 'The AI service requires administrator authentication.'
SECRET = '<html>selector=#private token=SECRET https://private/credential</html>'


class PublicErrors(unittest.TestCase):
    def test_validation_and_message_vocabulary(self):
        for code in ['JV-SVC-103', 'JV-SVC-002', 'JV-TIMEOUT-001', 'JV-FUTURE-999',
                     'JV-AGENT-PROVIDER-CLEANUP-001']:
            self.assertEqual(public_remote_error({'error': {'code': code, 'message': AUTH}}).code, code)
            for message in [SECRET, 'x' * 257, AUTH + '\n', {'message': AUTH}]:
                self.assertIsNone(public_remote_error({'error_code': code, 'error_message': message}).message)
        for code in ['engine_error', 'JV-SVC-103\n', 'JV-SVC-001/secret', 'JV-secret-001',
                     'JV-' + 'A' * 30 + '-001', 103, None]:
            self.assertIsNone(public_remote_error({'error_code': code, 'error_message': AUTH}))

    def client(self, job):
        client = JvApiClient(JvClientConfig(base_url='http://127.0.0.1:9', wait_timeout=.025, poll_interval=.01))
        client._token = 'SYNTHETIC_TOKEN'
        # Real get_job validates identity/status/JSON; no remote network exists.
        client._open = Mock(side_effect=lambda *a, **kw: self.response(job))
        client.submit_job = Mock(return_value={'id': 'job_1', 'conversation_id': 'conv_1', 'status': 'queued'})
        return client

    @staticmethod
    def response(job):
        response = io.BytesIO(json.dumps({'id': 'job_1', 'conversation_id': 'conv_1', **job}).encode())
        response.status = 200
        return response

    def test_waiting_auth_timeout_is_a_local_deadline(self):
        client = self.client({'status': 'waiting_for_auth', 'error_code': 'JV-SVC-103', 'error_message': AUTH})
        with self.assertRaises(JvError) as caught:
            client.wait_for_job('job_1')
        self.assertNotIsInstance(caught.exception, RemoteInferenceError)
        self.assertIn('Timed out waiting', str(caught.exception))

    def test_structured_preserves_public_code_without_changing_retry_classification(self):
        for code in ['JV-SVC-103', 'JV-SVC-002', 'JV-TIMEOUT-001']:
            error = StructuredProcessor._failed({'error': {'code': code, 'message': SECRET}})
            self.assertEqual(error.public_error.code, code)
            self.assertIsNone(error.public_error.message)
            self.assertEqual(error.failure_code, 'agent_inference_failed')
            self.assertNotIn('SECRET', str(error))

    def test_job_to_bridge_and_next_local_failure(self):
        cases = [('failed', code) for code in ['JV-SVC-103', 'JV-SVC-002', 'JV-TIMEOUT-001', 'malformed']]
        cases += [('structured', code) for code in ['JV-SVC-103', 'JV-SVC-002', 'JV-TIMEOUT-001']]
        for status, code in cases:
            with self.subTest(status=status, code=code), tempfile.TemporaryDirectory() as td:
                client = self.client({'status': status, 'error_code': code,
                                      'error_message': AUTH if code == 'JV-SVC-103' else SECRET})
                processor = None
                if status == 'structured':
                    from test_structured_core import core_request
                    processor = AgentProcessor(client, Path(td) / 'structured')
                    client.create_response = Mock(return_value={'id': 'response_1', 'object': 'response',
                        'status': 'failed', 'output': [], 'error': {'code': code, 'message': AUTH if code == 'JV-SVC-103' else SECRET}})
                runtime = AdapterRuntime(client, processor=processor)
                port = runtime.start()
                try:
                    session = cli.SessionRuntime(Path(td), 'session', Path(td), {}, 'fixture', [],
                                                 runtime, 1, [], True, False)
                    out = Mock()
                    bridge = Bridge(out, Path(td))
                    bridge.session = session
                    bridge.client = client
                    bridge.turn_id, bridge.turn_request = 'turn1', 'request1'

                    def engine(*args, **kwargs):
                        body = core_request() if processor else {'input': 'synthetic', 'tools': []}
                        body['stream'] = False
                        request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                            data=json.dumps(body).encode(),
                            headers={'Authorization': 'Bearer ' + runtime.key, 'Content-Type': 'application/json'})
                        try:
                            urllib.request.urlopen(request, timeout=2)
                            self.fail('Remote failure should fail the adapter request')
                        except urllib.error.HTTPError as exc:
                            self.assertNotIn(b'SECRET', exc.read())
                        return 1, None

                    with patch.object(cli, '_run_engine', side_effect=engine):
                        bridge.worker = threading.Thread(target=bridge._turn, args=('synthetic',))
                        bridge.worker.start()
                        bridge.worker.join(3)
                        self.assertFalse(bridge.worker.is_alive())
                        bridge.reap()
                    event = out.emit.call_args.args[0]
                    self.assertEqual(event['type'], 'turn.failed')
                    self.assertEqual(event['code'], 'engine_error')  # Old consumers still work.
                    if code != 'malformed':
                        self.assertEqual(event['support_code'], code)
                        self.assertEqual(event['source'], 'remote')
                    else:
                        self.assertNotIn('support_code', event)
                    self.assertNotIn('SECRET', json.dumps(event))
                    self.assertEqual(event.get('public_message'), AUTH if code == 'JV-SVC-103' else None)
                    # A new local engine failure cannot reuse the previous remote error.
                    with patch.object(cli, '_run_engine', return_value=(1, None)):
                        bridge.worker = threading.Thread(target=bridge._turn, args=('local failure',))
                        bridge.worker.start()
                        bridge.worker.join(3)
                        bridge.reap()
                    self.assertNotIn('support_code', out.emit.call_args.args[0])
                finally:
                    runtime.close()

    def test_waiting_status_survives_recovery_failure_or_cancellation(self):
        for outcome in ('succeeded', 'failed', 'cancelled'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as td:
                client = self.client({})
                client.config.wait_timeout = None
                waiting_seen, resume, running_seen, finish = [threading.Event() for _ in range(4)]
                polls = []
                def poll(request, *args, **kwargs):
                    polls.append(request.full_url)
                    if len(polls) == 1:
                        return self.response({'status': 'waiting_for_auth', 'error_code': 'JV-SVC-103', 'error_message': AUTH})
                    if len(polls) == 2:
                        waiting_seen.set()
                        if not resume.wait(3):
                            raise AssertionError('Test did not release auth wait')
                        return self.response({'status': 'running'})
                    running_seen.set()
                    if not finish.wait(3):
                        raise AssertionError('Test did not release terminal result')
                    return self.response({'status': outcome, 'answer': '{"type":"final","text":"done"}',
                        'error_code': 'JV-TIMEOUT-001' if outcome == 'failed' else None, 'error_message': SECRET})
                client._open = Mock(side_effect=poll)
                runtime = AdapterRuntime(client)
                port = runtime.start()
                session = cli.SessionRuntime(Path(td), 'session', Path(td), {}, 'fixture', [], runtime, None, [], True, False)
                out = Mock()
                bridge = Bridge(out, Path(td))
                bridge.session, bridge.client = session, client
                bridge.turn_id, bridge.turn_request = 'same_turn', 'same_request'
                def engine(*args, **kwargs):
                    request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                        data=json.dumps({'input':'synthetic', 'tools':[], 'stream':False}).encode(),
                        headers={'Authorization':'Bearer '+runtime.key, 'Content-Type':'application/json'})
                    try:
                        with urllib.request.urlopen(request, timeout=5) as response:
                            response.read()
                        return 0, None
                    except urllib.error.HTTPError:
                        return 1, None
                try:
                    with patch.object(cli, '_run_engine', side_effect=engine):
                        bridge.worker = threading.Thread(target=bridge._turn, args=('synthetic',))
                        bridge.worker.start()
                        self.assertTrue(waiting_seen.wait(2))
                        bridge.reap()
                        notice = out.emit.call_args.args[0]
                        self.assertEqual(notice, {'type':'turn.status', 'turn_id':'same_turn', 'source':'remote',
                            'status':'waiting_for_auth', 'support_code':'JV-SVC-103', 'public_message':AUTH})
                        self.assertTrue(bridge.worker.is_alive())
                        count = out.emit.call_count
                        for _ in range(10): bridge.reap()
                        self.assertEqual(out.emit.call_count, count)  # No poll spam.
                        bridge.request({'type':'turn.start','request_id':'duplicate','text':'duplicate'})
                        self.assertEqual(out.emit.call_args.args[0]['code'], 'turn_busy')
                        if outcome == 'cancelled':
                            bridge.request({'type':'turn.cancel','request_id':'stop','turn_id':'same_turn'})
                        resume.set()
                        if outcome != 'cancelled':
                            self.assertTrue(running_seen.wait(2))
                            bridge.reap()
                            self.assertEqual(out.emit.call_args.args[0], {'type':'turn.status', 'turn_id':'same_turn',
                                'source':'remote', 'status':'running'})
                        finish.set()
                        bridge.worker.join(3)
                        self.assertFalse(bridge.worker.is_alive())
                        bridge.reap()
                    terminal = out.emit.call_args.args[0]
                    self.assertEqual(terminal['type'], {'succeeded':'turn.completed','failed':'turn.failed','cancelled':'turn.cancelled'}[outcome])
                    self.assertEqual(terminal['turn_id'], 'same_turn')
                    self.assertEqual(terminal.get('support_code'), 'JV-TIMEOUT-001' if outcome == 'failed' else None)
                    client.submit_job.assert_called_once()
                    self.assertTrue(all(url.endswith('/v1/jobs/job_1') for url in polls))
                    self.assertNotIn('SECRET', str(out.emit.call_args_list))
                finally:
                    resume.set(); finish.set()
                    if bridge.worker: bridge.worker.join(3)
                    runtime.close()
