"""Contract and restart-safety coverage for opt-in structured Responses mode."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli.adapter import AdapterRuntime
from jvcli.safety import JvError, ProtocolError, SubmissionUncertain
from jvcli.structured import (DurableResponseState, STRUCTURED_AGENT_INSTRUCTIONS,
                              StructuredProcessor)
from jvcli.transport import JvApiClient, JvClientConfig


def response(status='completed', output=None, response_id='response_1', error=None):
    return {'id': response_id, 'object': 'response', 'status': status,
            'output': [] if output is None else output, 'error': error}


def message(text='done'):
    return {'type': 'message', 'id': 'msg_1', 'status': 'completed',
            'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': text, 'annotations': []}]}


def tool(arguments='{"command":"pwd"}', *, name='shell_command', call_id='call_1'):
    return {'type': 'function_call', 'id': 'fc_1', 'call_id': call_id,
            'status': 'completed', 'name': name, 'arguments': arguments}


def local_request():
    return {
        'model': 'jv-local', 'instructions': STRUCTURED_AGENT_INSTRUCTIONS,
        'input': [{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'show the current directory'}]}],
        'tools': [
            {'type': 'function', 'name': 'shell_command', 'description': 'Run locally',
             'strict': False, 'parameters': {
                 'type': 'object', 'properties': {
                     'command': {'type': 'string'}, 'workdir': {'type': 'string'}},
                 'required': ['command'], 'additionalProperties': False}},
            {'type': 'custom', 'name': 'apply_patch'},
            {'type': 'function', 'name': 'view_image', 'parameters': {'type': 'object'}},
        ],
        'tool_choice': 'auto', 'parallel_tool_calls': True,
        'reasoning': {'summary': 'auto'}, 'store': False, 'stream': True,
        'include': ['reasoning.encrypted_content'], 'prompt_cache_key': 'thread_1',
        'client_metadata': {'session_id': 'synthetic'},
    }


class FakeStructuredClient:
    _token = None

    def __init__(self, creates, waits=()):
        self.creates = list(creates)
        self.waits = list(waits)
        self.posts = []
        self.config = JvClientConfig(base_url='http://127.0.0.1', request_timeout=1,
                                     poll_interval=.01, wait_timeout=1)

    def create_response(self, body, key):
        self.posts.append((json.loads(json.dumps(body)), key))
        value = self.creates.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def wait_for_response(self, response_id, *, progress=None, **kwargs):
        value = self.waits.pop(0)
        if progress:
            progress(value)
        return value


class StructuredProcessorTests(unittest.TestCase):
    def test_restart_reconciles_uncertain_post_with_saved_key(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, client, _ = self.make_runtime(td, [
                SubmissionUncertain('lost'), SubmissionUncertain('lost again')])
            with self.assertRaises(SubmissionUncertain):
                runtime.process_request(local_request())
            restarted, new_client, _ = self.make_runtime(td, [response(output=[message()])])
            restarted.process_request(local_request())
            self.assertEqual(client.posts[0], new_client.posts[0])

    def test_distinct_round_cannot_reuse_response_or_call_id(self):
        for reuse in ('response', 'call'):
            with self.subTest(reuse=reuse), tempfile.TemporaryDirectory() as td:
                next_call = tool()
                next_call['id'] = 'fc_2'
                next_response = response(output=[next_call],
                    response_id='response_1' if reuse == 'response' else 'response_2')
                runtime, client, _ = self.make_runtime(td, [response(output=[tool()]), next_response])
                request = local_request()
                call = runtime.process_request(request)[0]
                request['input'] += [call, {'type': 'function_call_output',
                    'call_id': call['call_id'], 'output': 'actual result'}]
                with self.assertRaisesRegex(ProtocolError, 'replayed'):
                    runtime.process_request(request)
                self.assertNotEqual(client.posts[0][1], client.posts[1][1])

    def test_persistence_failure_blocks_further_submission(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            runtime, client, _ = self.make_runtime(td, [])
            with patch('jvcli.structured.atomic_write', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(JvError, 'could not be saved'):
                    runtime.process_request(local_request())
            with self.assertRaisesRegex(JvError, 'persistence failed'):
                runtime.process_request(local_request())
            self.assertEqual(client.posts, [])

    def make_runtime(self, directory, creates, waits=()):
        client = FakeStructuredClient(creates, waits)
        processor = StructuredProcessor(client, Path(directory) / 'structured')
        runtime = AdapterRuntime(client, processor=processor)
        runtime.begin_turn()
        return runtime, client, processor

    def test_structured_create_translation_and_mandatory_fields(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, client, _ = self.make_runtime(td, [response(output=[message()])])
            self.assertEqual(runtime.process_request(local_request())[0]['content'][0]['text'], 'done')
            body, key = client.posts[0]
            self.assertEqual(body['model'], 'jv-ai')
            self.assertTrue(body['background'])
            self.assertTrue(body['store'])
            self.assertFalse(body['stream'])
            self.assertFalse(body['parallel_tool_calls'])
            self.assertRegex(key, r'^jvcli-[0-9a-f]{48}$')
            self.assertEqual([(item['type'], item['name']) for item in body['tools']],
                             [('function', 'shell_command')])
            self.assertTrue(body['tools'][0]['strict'])
            self.assertEqual(set(body['tools'][0]['parameters']['properties']), {'command'})
            self.assertNotIn('RESPONSE CONTRACT', body['instructions'])
            self.assertEqual(body['input'], [
                {'role': 'user', 'content': 'show the current directory'}])
            self.assertEqual(runtime.response_repairs, 0)

    def test_polling_and_function_call_output_continuation(self):
        first = response('queued', response_id='response_first')
        first_done = response(output=[tool()], response_id='response_first')
        second = response(output=[message('continued')], response_id='response_second')
        with tempfile.TemporaryDirectory() as td:
            runtime, client, _ = self.make_runtime(td, [first, second], [first_done])
            request = local_request()
            call = runtime.process_request(request)[0]
            request2 = local_request()
            request2['input'] += [call, {'type': 'function_call_output',
                                         'call_id': call['call_id'], 'output': 'actual cwd'}]
            result = runtime.process_request(request2)[0]
            self.assertEqual(result['content'][0]['text'], 'continued')
            with self.assertRaisesRegex(ProtocolError, 'twice'):
                runtime.process_request(request)
            continuation = client.posts[1][0]
            self.assertEqual(continuation['previous_response_id'], 'response_first')
            self.assertEqual(continuation['input'], [{
                'type': 'function_call_output', 'call_id': 'call_1', 'output': 'actual cwd'}])
            self.assertEqual(continuation['tools'][0]['name'], 'shell_command')
            self.assertEqual(continuation['instructions'], STRUCTURED_AGENT_INSTRUCTIONS)
            state = json.loads((Path(td) / 'structured/state.json').read_text())
            self.assertEqual(state['rounds'][0]['phase'], 'continued')
            self.assertEqual(state['rounds'][1]['phase'], 'final')

    def test_ambiguous_post_reconciles_with_same_key_and_body(self):
        uncertain = SubmissionUncertain('lost response')
        with tempfile.TemporaryDirectory() as td:
            runtime, client, _ = self.make_runtime(
                td, [uncertain, response(output=[message()])])
            runtime.process_request(local_request())
            self.assertEqual(len(client.posts), 2)
            self.assertEqual(client.posts[0], client.posts[1])
            saved = json.loads((Path(td) / 'structured/state.json').read_text())
            self.assertEqual(saved['rounds'][0]['uncertain_submissions'], 1)

    def test_same_key_same_body_and_different_body_failure(self):
        with tempfile.TemporaryDirectory() as td:
            state = DurableResponseState(Path(td) / 'state')
            index = state.prepare('a' * 64, {'model': 'jv-ai', 'input': []})
            item = state.rounds[index]
            self.assertIs(state.assert_key_body(item['key'], item['body']), item)
            with self.assertRaisesRegex(ProtocolError, 'different request body'):
                state.assert_key_body(item['key'], {'model': 'changed'})

    def test_tool_is_persisted_before_publication_and_never_republished(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, _, _ = self.make_runtime(td, [response(output=[tool()])])
            request = local_request()
            runtime.process_request(request)
            state_path = Path(td) / 'structured/state.json'
            saved = json.loads(state_path.read_text())
            self.assertEqual(saved['rounds'][0]['phase'], 'published')
            self.assertEqual(saved['rounds'][0]['output']['call_id'], 'call_1')
            with self.assertRaisesRegex(ProtocolError, 'twice'):
                runtime.process_request(request)
            restarted, _, _ = self.make_runtime(td, [])
            with self.assertRaisesRegex(ProtocolError, 'twice'):
                restarted.process_request(request)
            changed = local_request()
            changed['input'][0]['content'][0]['text'] = 'new task'
            with self.assertRaisesRegex(ProtocolError, 'unresolved'):
                restarted.process_request(changed)

    def test_completed_output_validation_fails_closed(self):
        invalid = [
            response(output=[]),
            response(output=[message(), message('two')]),
            response(output=[{'type': 'unknown', 'id': 'x', 'status': 'completed'}]),
            response(output=[{**message(), 'id': '../bad'}]),
            response(output=[{**message(), 'role': 'user'}]),
            response(output=[{**message(), 'content': []}]),
        ]
        for payload in invalid:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as td:
                runtime, _, _ = self.make_runtime(td, [payload])
                with self.assertRaises(JvError):
                    runtime.process_request(local_request())
                saved = json.loads((Path(td) / 'structured/state.json').read_text())
                self.assertNotEqual(saved['rounds'][0]['phase'], 'published')

    def test_function_call_validation_rejects_unknown_bad_json_and_schema(self):
        invalid = [tool(name='view_image'), tool(arguments='{'),
                   tool(arguments='[]'), tool(arguments='{}'),
                   tool(call_id='../bad'), tool(arguments='{"command":2}'),
                   tool(arguments='{"command":"pwd","extra":1}')]
        for call in invalid:
            with self.subTest(call=call), tempfile.TemporaryDirectory() as td:
                runtime, _, _ = self.make_runtime(td, [response(output=[call])])
                with self.assertRaises(ProtocolError):
                    runtime.process_request(local_request())

    def test_failed_response_and_nonterminal_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            failed = response('failed', error={'code': 'provider_failed', 'message': 'safe failure'})
            runtime, _, _ = self.make_runtime(td, [failed])
            with self.assertRaisesRegex(JvError, 'provider_failed'):
                runtime.process_request(local_request())
        with tempfile.TemporaryDirectory() as td:
            bad = response('queued', output=[message()])
            runtime, _, _ = self.make_runtime(td, [bad])
            with self.assertRaises(JvError):
                runtime.process_request(local_request())

    def test_changed_call_or_output_and_unexpected_call_id_fail(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, _, _ = self.make_runtime(
                td, [response(output=[tool()]),
                     response(output=[message()], response_id='response_2')])
            request = local_request()
            call = runtime.process_request(request)[0]
            changed = dict(call)
            changed['arguments'] = '{"command":"changed"}'
            bad_call = local_request()
            bad_call['input'] += [changed, {'type': 'function_call_output',
                                             'call_id': call['call_id'], 'output': 'result'}]
            with self.assertRaises(ProtocolError):
                runtime.process_request(bad_call)
            request2 = local_request()
            request2['input'] += [call, {'type': 'function_call_output',
                                         'call_id': call['call_id'], 'output': 'result'}]
            runtime.process_request(request2)
            changed_output = local_request()
            changed_output['input'] += [call, {'type': 'function_call_output',
                                                'call_id': call['call_id'], 'output': 'changed'}]
            with self.assertRaisesRegex(ProtocolError, 'changed structured function output'):
                runtime.process_request(changed_output)
            request3 = local_request()
            request3['input'].append({'type': 'function_call_output',
                                      'call_id': 'call_unknown', 'output': 'result'})
            with self.assertRaises(ProtocolError):
                runtime.process_request(request3)

    def test_unsupported_codex_fields_content_and_tools_fail_or_are_filtered(self):
        cases = []
        unknown = local_request(); unknown['web_search'] = True; cases.append(unknown)
        image = local_request(); image['input'][0]['content'] = [
            {'type': 'input_image', 'image_url': 'data:image/png;base64,x'}]; cases.append(image)
        custom_output = local_request(); custom_output['input'].append(
            {'type': 'custom_tool_call_output', 'call_id': 'call_1', 'output': 'x'}); cases.append(custom_output)
        for request in cases:
            with self.subTest(request=request), tempfile.TemporaryDirectory() as td:
                runtime, client, _ = self.make_runtime(td, [])
                with self.assertRaises(ProtocolError):
                    runtime.process_request(request)
                self.assertEqual(client.posts, [])
        with tempfile.TemporaryDirectory() as td:
            required = local_request()
            required['tools'] = [{'type': 'custom', 'name': 'apply_patch'}]
            required['tool_choice'] = 'required'
            runtime, _, _ = self.make_runtime(td, [])
            with self.assertRaisesRegex(ProtocolError, 'no certified'):
                runtime.process_request(required)


class WireServer:
    def __init__(self):
        self.posts = []
        self.polls = []
        self.create_status = 202
        self.create_payload = response('queued')
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, payload):
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                owner.posts.append((self.path, dict(self.headers), raw))
                self.reply(owner.create_status, owner.create_payload)

            def do_GET(self):
                payload = owner.polls.pop(0)
                self.reply(200, payload)

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_address[1]}'

    def close(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(1)


class StructuredTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = WireServer()
        self.client = JvApiClient(JvClientConfig(
            base_url=self.server.base, poll_interval=.001,
            request_timeout=1, wait_timeout=1))
        self.client._token = 'SYNTHETIC-TOKEN'

    def tearDown(self):
        self.server.close()

    def test_create_202_headers_and_normalized_body(self):
        body = {'stream': False, 'model': 'jv-ai'}
        result = self.client.create_response(body, 'durable:key-1')
        self.assertEqual(result['status'], 'queued')
        path, headers, raw = self.server.posts[0]
        self.assertEqual(path, '/v1/responses')
        self.assertEqual(headers['Authorization'], 'Bearer SYNTHETIC-TOKEN')
        self.assertEqual(headers['X-Jv-Csrf'], '1')
        self.assertEqual(headers['Idempotency-Key'], 'durable:key-1')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(raw, b'{"model":"jv-ai","stream":false}')

    def test_create_200_exact_replay_is_accepted(self):
        self.server.create_status = 200
        self.assertEqual(self.client.create_response(
            {'model': 'jv-ai'}, 'replay_1')['id'], 'response_1')

    def test_poll_queued_in_progress_completed(self):
        self.server.polls = [response('queued'), response('in_progress'),
                             response(output=[message()])]
        statuses = []
        result = self.client.wait_for_response('response_1', progress=lambda x: statuses.append(x['status']))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(statuses, ['queued', 'in_progress', 'completed'])

    def test_poll_response_id_mismatch_and_nonterminal_output_fail(self):
        for payload in (response('queued', response_id='response_other'),
                        response('in_progress', output=[message()])):
            with self.subTest(payload=payload):
                self.server.polls = [payload]
                with self.assertRaises(JvError):
                    self.client.get_response('response_1')

    def test_create_malformed_metadata_is_submission_uncertain(self):
        self.server.create_payload = {'id': '../bad', 'object': 'response',
                                      'status': 'queued', 'output': []}
        with self.assertRaisesRegex(SubmissionUncertain, 'reuse idempotency key'):
            self.client.create_response({'model': 'jv-ai'}, 'same-key')


if __name__ == '__main__':
    unittest.main()
