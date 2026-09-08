"""Image HTTP bridge, durable replay and workspace ingress regressions."""
import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import urllib.error
import urllib.request
import zlib

from test_structured import (FakeStructuredClient, WireServer, local_request,
                             response, message, tool)
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.images import snapshot_images
from jvcli.safety import ProtocolError, SubmissionUncertain, redact
from jvcli.structured import StructuredProcessor
from jvcli.transport import JvApiClient, JvClientConfig


def png():
    def chunk(t, data):
        return struct.pack('>I', len(data)) + t + data + struct.pack('>I', zlib.crc32(t + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0' + b'\xff\0\0' * 2 + b'\0' + b'\xff\0\0' * 2))
            + chunk(b'IEND', b''))


def image(data=None):
    return {'type': 'input_image', 'image_url': 'data:image/png;base64,' +
            base64.b64encode(png() if data is None else data).decode(), 'detail': 'high'}


class ImageBridgeTests(unittest.TestCase):
    def test_large_plain_text_still_obeys_metadata_limit(self):
        for content in ('x' * (101 * 1024), [{'role': 'user', 'content': 'x' * (101 * 1024)}]):
            with self.assertRaisesRegex(ProtocolError, 'metadata'):
                JvApiClient.normalized_response_body({'input': content})

    def test_image_tool_result_rejected_over_http_with_no_remote_continuation(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeStructuredClient([response(output=[tool()])])
            runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
            request = local_request()
            call = runtime.process_request(request)[0]
            request['stream'] = False
            request['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': [image()]}]
            port = runtime.start()
            try:
                wire = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                    data=json.dumps(request).encode(), headers={
                        'Authorization': 'Bearer ' + runtime.key, 'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(wire, timeout=3)
                with caught.exception as error:
                    self.assertEqual(error.code, 400)
                    detail = error.read().decode()
                    self.assertIn('published view_image', detail)
                    self.assertNotIn(image()['image_url'].split(',')[1], detail)
                self.assertEqual(len(client.posts), 1)
            finally:
                runtime.close()

    def test_custom_patch_rejected_over_loopback_without_execution(self):
        with tempfile.TemporaryDirectory() as td:
            client = FakeStructuredClient([])
            runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
            port = runtime.start()
            try:
                request = local_request()
                request['stream'] = False
                request['tools'] = [{'type': 'custom', 'name': 'apply_patch', 'format': {
                    'type': 'grammar', 'syntax': 'lark', 'definition': 'start: "*** Begin Patch"'}}]
                request['tool_choice'] = 'required'
                wire = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                    data=json.dumps(request).encode(), headers={
                        'Authorization': 'Bearer ' + runtime.key, 'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(wire, timeout=3)
                with caught.exception as error:
                    self.assertEqual(error.code, 400)
                    self.assertIn('exact certified', error.read().decode())
                self.assertEqual(client.posts, [])
                self.assertEqual(runtime.response_repairs, 0)
            finally:
                runtime.close()

    def test_image_crosses_both_http_boundaries_and_continues_without_replay(self):
        remote = WireServer()
        try:
            client = JvApiClient(JvClientConfig(base_url=remote.base, poll_interval=.001))
            client._token = 'SYNTHETIC-TOKEN'
            remote.create_status = 200
            remote.create_payload = response(output=[tool()])
            with tempfile.TemporaryDirectory() as td:
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                port = runtime.start()
                try:
                    request = local_request()
                    request['stream'] = False
                    request['input'][0]['content'] = [
                        {'type': 'input_text', 'text': 'before'}, image(),
                        {'type': 'input_text', 'text': 'after'}, image()]
                    def post(body):
                        req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                            data=json.dumps(body).encode(), headers={
                                'Authorization': 'Bearer ' + runtime.key,
                                'Content-Type': 'application/json'})
                        with urllib.request.urlopen(req, timeout=3) as handle:
                            return json.load(handle)
                    first = post(request)
                    sent = json.loads(remote.posts[0][2])
                    self.assertEqual(sent['input'][0]['content'], request['input'][0]['content'])
                    call = first['output'][0]
                    request['input'] += [call, {'type': 'function_call_output',
                        'call_id': call['call_id'], 'output': 'exit 0: actual local output'}]
                    remote.create_payload = response(output=[message()], response_id='response_2')
                    post(request)
                    sent2 = json.loads(remote.posts[1][2])
                    self.assertEqual(sent2['previous_response_id'], 'response_1')
                    self.assertEqual(sent2['input'], [request['input'][-1]])
                    self.assertNotEqual(remote.posts[0][1]['Idempotency-Key'], remote.posts[1][1]['Idempotency-Key'])
                    self.assertEqual(runtime.response_repairs, 0)
                finally:
                    runtime.close()
        finally:
            remote.close()

    def test_large_image_restart_reuses_exact_durable_body(self):
        with tempfile.TemporaryDirectory() as td:
            request = local_request()
            # Signature preflight is deliberately not a full decoder; JV owns decoding.
            request['input'][0]['content'] = [image(png() + b'\0' * (1024 * 1024))]
            client = FakeStructuredClient([SubmissionUncertain('lost'), SubmissionUncertain('lost')])
            runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
            with self.assertRaises(SubmissionUncertain):
                runtime.process_request(request)
            next_client = FakeStructuredClient([response(output=[message()])])
            restarted = AdapterRuntime(next_client, processor=StructuredProcessor(next_client, Path(td)))
            restarted.process_request(request)
            self.assertEqual(client.posts[0], next_client.posts[0])
            self.assertEqual(os.stat(Path(td) / 'state.json').st_mode & 0o777, 0o600)

    def test_invalid_images_rejected_before_submission(self):
        cases = [
            [{**image(), 'image_url': 'file:///etc/passwd'}],
            [{**image(), 'image_url': 'https://example.com/image.png'}],
            [{**image(), 'detail': 'original'}],
            [{**image(), 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(png()).decode()}],
            [{**image(), 'image_url': 'data:image/png;base64,!'}],
            [{**image(), 'path': '/etc/passwd'}],
            [image()] * 5,
            [image(png() + b'x' * (5 * 1024 * 1024))],
            [image(png() + b'x' * (4 * 1024 * 1024))] * 3,
            [image(), {'type': 'input_audio', 'audio_url': 'data:audio/wav;base64,AAAA'}],
            [image(), {'type': 'input_file', 'file_id': 'file_unsupported'}],
        ]
        for parts in cases:
            with self.subTest(parts_count=len(parts)), tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([])
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                request = local_request()
                request['input'][0]['content'] = parts
                with self.assertRaises(ProtocolError):
                    runtime.process_request(request)
                self.assertEqual(client.posts, [])

    def test_view_image_array_and_custom_output_fail_closed(self):
        for result in ([image()], [{'type': 'input_text', 'text': 'ok'}], [{'type': 'unknown'}]):
            with tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([response(output=[tool()])])
                runtime = AdapterRuntime(client, processor=StructuredProcessor(client, Path(td)))
                request = local_request()
                call = runtime.process_request(request)[0]
                request['input'] += [call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': result}]
                with self.assertRaises(ProtocolError):
                    runtime.process_request(request)
                self.assertEqual(len(client.posts), 1)
                self.assertEqual(runtime.response_repairs, 0)

    def test_redaction_hides_image_bytes(self):
        value = image()['image_url']
        self.assertNotIn(value.split(',')[1], redact('error: ' + value))


class ImageIngressTests(unittest.TestCase):
    def test_snapshot_and_parser(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / 'workspace'; workspace.mkdir()
            source = workspace / 'image.png'; source.write_bytes(png())
            snapshots = snapshot_images([str(source)], workspace, Path(td) / 'snapshots')
            source.write_bytes(b'changed')
            self.assertEqual(snapshots[0].read_bytes(), png())
            self.assertEqual(snapshots[0].stat().st_mode & 0o777, 0o600)
            args = cli._parser().parse_args(['exec', '--image', 'image.png', 'inspect'])
            self.assertEqual(args.image, ['image.png'])

    def test_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); workspace = root / 'workspace'; workspace.mkdir()
            outside = root / 'outside.png'; outside.write_bytes(png())
            (workspace / 'link.png').symlink_to(outside)
            (workspace / 'dir').symlink_to(root, target_is_directory=True)
            for name in ('../outside.png', str(outside), 'link.png', 'dir/outside.png'):
                with self.subTest(name=name), self.assertRaises(ProtocolError):
                    snapshot_images([name], workspace, root / 'snapshots')

    def test_fifo_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); os.mkfifo(root / 'pipe.png')
            with self.assertRaises(ProtocolError):
                snapshot_images(['pipe.png'], root, root / 'snapshots')
