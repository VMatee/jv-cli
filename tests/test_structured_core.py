"""Certified custom and image result paths across both real HTTP bridge boundaries."""
import copy
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.request

from test_structured import FakeStructuredClient, WireServer, local_request, response, message, tool
from test_structured_images import image
from jvcli.adapter import AdapterRuntime
from jvcli.safety import ProtocolError, SubmissionUncertain
from jvcli.structured import StructuredProcessor, PATCH_DESCRIPTION, PATCH_GRAMMAR_SHA256
from jvcli.transport import JvApiClient, JvClientConfig


def core_request():
    request = local_request()
    request['tools'] = [request['tools'][0],
        {'type': 'function', 'name': 'update_plan', 'description': 'Plan', 'strict': False,
         'parameters': {'type': 'object', 'properties': {
             'explanation': {'type': 'string'}, 'plan': {'type': 'array', 'items': {
                 'type': 'object', 'properties': {'step': {'type': 'string'},
                     'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'completed']}},
                 'required': ['step', 'status'], 'additionalProperties': False}}},
             'required': ['plan'], 'additionalProperties': False}},
        {'type': 'custom', 'name': 'apply_patch', 'description': PATCH_DESCRIPTION,
         'format': {'type': 'grammar', 'syntax': 'lark', 'definition':
             (Path(__file__).resolve().parents[1] / 'lib/jvcli/apply_patch.lark').read_text()}},
        {'type': 'function', 'name': 'view_image', 'description': 'Inspect local image.',
         'strict': False, 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}},
                                       'required': ['path'], 'additionalProperties': False}}]
    return request


def patch_call():
    return {'type': 'custom_tool_call', 'id': 'ctc_1', 'call_id': 'patch_1', 'name': 'apply_patch',
            'input': '*** Begin Patch\n*** Add File: example.txt\n+ exact \\n text\n*** End Patch\n'}


class CoreBridgeTests(unittest.TestCase):
    def test_forwarded_function_schemas_are_strict_server_subsets(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeStructuredClient([response(output=[message()])])
            AdapterRuntime(client, processor=StructuredProcessor(client, Path(td))).process_request(core_request())
            for tool in client.posts[0][0]['tools']:
                if tool['type'] != 'function':
                    continue
                self.assertTrue(tool['strict'])
                self.assertEqual(set(tool['parameters']['properties']), set(tool['parameters']['required']))
            names = {tool['name']: tool for tool in client.posts[0][0]['tools']}
            self.assertEqual(set(names['shell_command']['parameters']['properties']), {'command'})
            self.assertEqual(set(names['update_plan']['parameters']['properties']), {'plan'})

    def test_jpeg_webp_order_bytes_and_detail_survive_http_transport(self):
        parts = []
        for ext, mime in (('jpg', 'image/jpeg'), ('webp', 'image/webp')):
            data = (Path(__file__).parent / 'fixtures' / ('core-image.' + ext)).read_bytes()
            parts.append({'type': 'input_image', 'image_url': 'data:' + mime + ';base64,' + base64.b64encode(data).decode(),
                          'detail': 'auto' if ext == 'jpg' else 'high'})
        remote = WireServer()
        try:
            remote.create_status = 200
            remote.create_payload = response(output=[tool('{"path":"x.jpg"}', name='view_image')])
            client = JvApiClient(JvClientConfig(base_url=remote.base, poll_interval=.001))
            client._token = 'SYNTHETIC-TOKEN'
            with tempfile.TemporaryDirectory() as td:
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                request = core_request(); request['input'][0]['content'] = parts
                call = runtime.process_request(request)[0]
                self.assertEqual(json.loads(remote.posts[0][2])['input'][0]['content'], parts)
                request['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': parts}]
                remote.create_payload = response(output=[message()], response_id='response_2')
                runtime.process_request(request)
                self.assertEqual(json.loads(remote.posts[1][2])['input'][0]['output'], parts)
        finally:
            remote.close()

    def test_custom_then_view_image_then_shell_over_both_http_boundaries(self):
        remote = WireServer()
        try:
            remote.create_status = 200
            client = JvApiClient(JvClientConfig(base_url=remote.base, poll_interval=.001))
            client._token = 'SYNTHETIC-TOKEN'
            with tempfile.TemporaryDirectory() as td:
                processor = StructuredProcessor(client, Path(td))
                runtime = AdapterRuntime(client, processor=processor)
                port = runtime.start()
                try:
                    request = core_request(); request['stream'] = False
                    outputs = [patch_call(), {**tool('{"path":"screenshot.png"}', name='view_image', call_id='view_2'), 'id': 'fc_2'},
                               {**tool(call_id='shell_3'), 'id': 'fc_3'}, message()]
                    results = [' Success.\nA example.txt\n', [image(), {**image(), 'detail': 'auto'}], 'Exit code: 1\nfailed test']
                    for i, output in enumerate(outputs):
                        remote.create_payload = response(output=[output], response_id=f'response_{i+1}')
                        wire = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses', data=json.dumps(request).encode(),
                            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + runtime.key})
                        with urllib.request.urlopen(wire, timeout=3) as stream:
                            published = json.load(stream)['output'][0]
                        self.assertEqual(published, output)
                        sent = json.loads(remote.posts[-1][2])
                        if i == 0:
                            self.assertEqual(sent['tools'][2], request['tools'][2])
                            self.assertEqual(hashlib.sha256(sent['tools'][2]['format']['definition'].encode()).hexdigest(), PATCH_GRAMMAR_SHA256)
                        else:
                            self.assertEqual(sent['previous_response_id'], f'response_{i}')
                            self.assertEqual(sent['input'], [request['input'][-1]])
                        if i < len(results):
                            request['input'] += [published, {'type': published['type'] + '_output',
                                'call_id': published['call_id'], 'output': results[i]}]
                    self.assertEqual(len({headers['Idempotency-Key'] for _, headers, _ in remote.posts}), 4)
                    self.assertEqual(runtime.response_repairs, 0)
                    self.assertEqual([r['phase'] for r in processor.state.rounds], ['continued'] * 3 + ['final'])
                finally:
                    runtime.close()
        finally:
            remote.close()

    def test_image_and_custom_uncertain_continuation_restart_preserves_exact_body(self):
        for first, value in ((patch_call(), ' unchanged whitespace \n'),
                             (tool('{"path":"x.png"}', name='view_image'), [image()])):
            with self.subTest(kind=first['type']), tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([response(output=[first]), SubmissionUncertain('lost'), SubmissionUncertain('lost')])
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                request = core_request(); call = runtime.process_request(request)[0]
                request['input'] += [call, {'type': call['type'] + '_output', 'call_id': call['call_id'], 'output': value}]
                with self.assertRaises(SubmissionUncertain): runtime.process_request(request)
                other = FakeStructuredClient([response(output=[message()], response_id='response_2')])
                resumed = AdapterRuntime(other, processor=StructuredProcessor(other, Path(td)))
                resumed.process_request(request)
                self.assertEqual(client.posts[-1], other.posts[0])
                self.assertNotEqual(client.posts[0][1], other.posts[0][1])
                changed = copy.deepcopy(request)
                changed['input'][-1]['output'] = 'changed' if isinstance(value, str) else [{**image(), 'detail': 'auto'}]
                with self.assertRaisesRegex(ProtocolError, 'changed'): resumed.process_request(changed)
                self.assertEqual(len(other.posts), 1)

    def test_custom_class_name_grammar_and_input_fail_closed(self):
        variants = []
        for change in ('grammar', 'syntax', 'name', 'description', 'extra'):
            r = core_request()
            t = r['tools'][2]
            if change == 'grammar': t['format']['definition'] += '\n'
            elif change == 'syntax': t['format']['syntax'] = 'regex'
            elif change == 'name': t['type'] = 'function'
            elif change == 'description': t['description'] += ' changed'
            else: t['unknown'] = True
            variants.append(r)
        for request in variants:
            with tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([])
                with self.assertRaises(ProtocolError):
                    AdapterRuntime(client, processor=StructuredProcessor(client, Path(td))).process_request(request)
                self.assertFalse(client.posts)
        for bad in ({**patch_call(), 'input': {}}, {**patch_call(), 'input': 'x' * 32769},
                    {**patch_call(), 'input': ' '}, {**patch_call(), 'name': 'unknown'},
                    {**patch_call(), 'arguments': '{}'}, tool(name='apply_patch')):
            with tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([response(output=[bad])])
                processor = StructuredProcessor(client, Path(td))
                with self.assertRaises(ProtocolError): AdapterRuntime(client, processor=processor).process_request(core_request())
                self.assertEqual(processor.state.rounds[0]['phase'], 'rejected')

    def test_wrong_result_class_call_id_patch_text_and_predecessor_rejected(self):
        for change in ('result_class', 'call_id', 'patch_text', 'predecessor', 'array', 'oversize'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([response(output=[patch_call()])])
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                request = core_request(); call = runtime.process_request(request)[0]
                request['input'] += [copy.deepcopy(call), {'type': 'custom_tool_call_output', 'call_id': call['call_id'], 'output': 'ok'}]
                if change == 'result_class': request['input'][-1]['type'] = 'function_call_output'
                elif change == 'call_id': request['input'][-1]['call_id'] = 'wrong'
                elif change == 'patch_text': request['input'][-2]['input'] += '\n'
                elif change == 'predecessor': request['previous_response_id'] = 'wrong'
                elif change == 'array': request['input'][-1]['output'] = [image()]
                else: request['input'][-1]['output'] = 'x' * 32769
                with self.assertRaises(ProtocolError): runtime.process_request(request)
                self.assertEqual(len(client.posts), 1)

    def test_invalid_image_results_never_submit(self):
        bad_outputs = [[], [image()] * 5, [{'type': 'input_text', 'text': 'no flatten'}],
            [image(), {'type': 'input_file', 'file_id': 'x'}], [{**image(), 'detail': 'original'}],
            [{**image(), 'image_url': 'file:///etc/passwd'}], [{'type': 'input_audio'}]]
        for value in bad_outputs:
            with tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([response(output=[tool('{"path":"x.png"}', name='view_image')])])
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                request = core_request(); call = runtime.process_request(request)[0]
                request['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': value}]
                with self.assertRaises(ProtocolError): runtime.process_request(request)
                self.assertEqual(len(client.posts), 1)

    def test_combined_initial_and_tool_result_image_limit_fails_before_continuation(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeStructuredClient([response(output=[tool('{"path":"x.png"}', name='view_image')])])
            runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
            request = core_request()
            request['input'][0]['content'] = [image()] * 4
            call = runtime.process_request(request)[0]
            request['input'] += [call, {'type': 'function_call_output',
                'call_id': call['call_id'], 'output': [image()]}]
            with self.assertRaisesRegex(ProtocolError, 'history exceeds'):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 1)
