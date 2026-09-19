"""Shared continuation and fail-closed remote failure regressions; no live API."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from jvcli.adapter import AdapterRuntime
from jvcli.agent import AgentProcessor
from jvcli.safety import JvError, SubmissionUncertain, UncertainToolSideEffect
from test_structured import FakeStructuredClient, response, tool
from test_structured_core import core_request


class ExecutionFailureTests(unittest.TestCase):
    def test_known_tool_result_is_delivered_once_and_failure_never_replays_action(self):
        for remote_code, failure_code in [
            ('JV-AGENT-PROVIDER-CLEANUP-001', 'provider_cleanup_failed'),
            ('JV-AGENT-INFERENCE-001', 'agent_inference_failed'),
            ('JV-AGENT-OUTPUT-001', 'remote_output_validation_failed'),
            ('PRIVATE_UNKNOWN', 'agent_inference_failed'),
        ]:
            with self.subTest(code=remote_code), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                command = "printf 'once\\n' >> side-effect.txt; printf 'AssertionError\\n'; exit 1"
                client = FakeStructuredClient([
                    response(output=[tool(json.dumps({'command': command}))]),
                    response('failed', response_id='response_2',
                             error={'code': remote_code, 'message': 'PRIVATE_MESSAGE'}),
                ])
                processor = AgentProcessor(client, root / 'state')
                runtime = AdapterRuntime(client, processor=processor)
                runtime.begin_turn()
                request = core_request()
                call = runtime.process_request(request)[0]
                outcome = subprocess.run(['/bin/sh', '-c', command], cwd=root,
                                         capture_output=True, text=True)
                result = f'Exit code: {outcome.returncode}\n' + outcome.stdout + outcome.stderr
                request['input'] += [call, {'type': 'function_call_output',
                    'call_id': call['call_id'], 'output': result}]
                sid = processor.state.value['agent']['session_id']
                with self.assertRaises(JvError) as caught:
                    runtime.process_request(request)
                self.assertEqual(caught.exception.failure_code, failure_code)
                self.assertNotIn('PRIVATE', str(caught.exception))
                self.assertEqual(client.posts[1][0]['input'], [{
                    'type': 'function_call_output', 'call_id': call['call_id'], 'output': result}])
                self.assertEqual(client.posts[1][0]['previous_response_id'], 'response_1')
                saved = copy.deepcopy(processor.state.value)
                self.assertEqual(saved['rounds'][-1]['failure_code'], failure_code)
                self.assertEqual(saved['rounds'][0]['phase'], 'continued')
                self.assertEqual(saved['agent']['interactions'][-1]['failure_code'], failure_code)
                self.assertNotIn('PRIVATE', saved['rounds'][-1]['error'])
                # Repeated local requests and process restart retain the same failure,
                # session and chain, with no remote inference or tool republication.
                with self.assertRaises(JvError):
                    runtime.process_request(request)
                restarted = AdapterRuntime(client, processor=AgentProcessor(client, root / 'state'))
                restarted.begin_turn()
                with self.assertRaises(JvError):
                    restarted.process_request(request)
                self.assertEqual(restarted.processor.state.value['agent']['session_id'], sid)
                self.assertEqual(len(client.posts), 2)
                self.assertEqual((root / 'side-effect.txt').read_text(), 'once\n')
                self.assertEqual(list(runtime.signatures.values()), [1])

    def test_expected_nonzero_and_complete_unicode_feedback_continue(self):
        with tempfile.TemporaryDirectory() as name:
            next_call = dict(tool('{"command":"cat app.py"}', call_id='call_2'), id='fc_2')
            client = FakeStructuredClient([
                response(output=[tool()]), response(output=[next_call], response_id='response_2')])
            runtime = AdapterRuntime(client, processor=AgentProcessor(client, Path(name)))
            request = core_request()
            call = runtime.process_request(request)[0]
            result = 'Exit code: 1\nTraceback:\nAssertionError\n' + ('  exact Ω ไทย \t\n' * 1500)
            request['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': result}]
            self.assertEqual(runtime.process_request(request)[0], next_call)
            self.assertEqual(client.posts[-1][0]['input'][0]['output'].encode(), result.encode())
            self.assertEqual(len(runtime.processor.state.value['agent']['tasks']), 1)

    def test_published_action_without_result_never_reexecutes(self):
        with tempfile.TemporaryDirectory() as name:
            client = FakeStructuredClient([response(output=[tool()])])
            processor = AgentProcessor(client, Path(name))
            runtime = AdapterRuntime(client, processor=processor)
            request = core_request()
            runtime.process_request(request)
            with self.assertRaises(UncertainToolSideEffect):
                runtime.process_request(request)
            restarted = AdapterRuntime(client, processor=AgentProcessor(client, Path(name)))
            with self.assertRaises(UncertainToolSideEffect):
                restarted.process_request(request)
            self.assertEqual(len(client.posts), 1)

    def test_lost_continuation_ack_reconciles_same_key_without_replaying_tool(self):
        with tempfile.TemporaryDirectory() as name:
            next_call = dict(tool('{"command":"cat app.py"}', call_id='call_2'), id='fc_2')
            client = FakeStructuredClient([
                response(output=[tool()]), SubmissionUncertain('lost acknowledgement'),
                response(output=[next_call], response_id='response_2')])
            runtime = AdapterRuntime(client, processor=AgentProcessor(client, Path(name)))
            request = core_request()
            call = runtime.process_request(request)[0]
            request['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': 'Exit code: 1\nAssertionError'}]
            self.assertEqual(runtime.process_request(request)[0], next_call)
            self.assertEqual(client.posts[1], client.posts[2])  # same body AND idempotency key
            self.assertEqual(len(runtime.processor.state.rounds), 2)
            self.assertEqual(list(runtime.signatures.values()), [1, 1])

    def test_ack_reconciliation_does_not_reset_repeated_action_guard(self):
        from jvcli.safety import ProtocolError

        with tempfile.TemporaryDirectory() as name:
            replies = []
            for n in range(1, 5):
                if n == 3:
                    replies.append(SubmissionUncertain('lost acknowledgement'))
                call = dict(tool('{"command":"false"}', call_id=f'call_{n}'), id=f'fc_{n}')
                replies.append(response(output=[call], response_id=f'response_{n}'))
            client = FakeStructuredClient(replies)
            runtime = AdapterRuntime(client, processor=AgentProcessor(client, Path(name)))
            request = core_request()
            for _ in range(3):
                call = runtime.process_request(request)[0]
                request['input'] += [call, {'type': 'function_call_output',
                    'call_id': call['call_id'], 'output': 'Exit code: 1\nfailed'}]
            with self.assertRaisesRegex(ProtocolError, 'same tool action four times'):
                runtime.process_request(request)
            self.assertEqual(client.posts[2], client.posts[3])
            self.assertEqual(list(runtime.signatures.values()), [3])
            self.assertEqual(len(runtime.processor.state.rounds), 4)
            self.assertEqual(runtime.processor.state.rounds[-1]['phase'], 'rejected')
