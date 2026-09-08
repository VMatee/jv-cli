#!/usr/bin/env python3
"""Pinned-engine protocol capture and supported structured coding checks; no live API.

All workspaces, browser profiles and histories are disposable under JV CLI state.
Captured reports omit message text, tool arguments and image data.
"""
from __future__ import annotations
import base64
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import struct
import sys
import uuid
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.images import snapshot_images
from jvcli.safety import JvError, private_dir
from jvcli.structured import StructuredProcessor
from jvcli.transport import JvClientConfig
from core_live_smoke import prepare_web


def tiny_png():
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0' + b'\xff\0\0' * 2 + b'\0' + b'\xff\0\0' * 2)) + chunk(b'IEND', b''))


class Script:
    _token = None
    config = JvClientConfig(request_timeout=1, wait_timeout=5, poll_interval=.01)

    def __init__(self, steps):
        self.steps = steps
        self.posts = []

    def create_response(self, body, key):
        index = len(self.posts)
        self.posts.append((body, key))
        if index >= len(self.steps):
            raise JvError('Unexpected extra scripted inference')
        name, arguments, required = self.steps[index]
        if index:
            result = body['input'][0]
            assert body['previous_response_id'] == f'response_{index}'
            assert result['call_id'] == f'call_{index}'
            assert result['type'] == ('custom_tool_call_output' if self.steps[index - 1][0] == 'apply_patch' else 'function_call_output')
            if required:
                assert isinstance(result['output'], str)
                assert required in result['output'], 'Expected actual tool output did not arrive'
            assert key != self.posts[-2][1]
        n = index + 1
        item = ({'type': 'function_call', 'id': f'fc_{n}', 'call_id': f'call_{n}',
                 'name': name, 'arguments': json.dumps(arguments), 'status': 'completed'}
                if name else {'type': 'message', 'id': f'msg_{n}', 'role': 'assistant',
                              'status': 'completed', 'content': [
                                  {'type': 'output_text', 'text': 'PARITY_SCRIPT_OK', 'annotations': []}]})
        if name == 'apply_patch':
            item = {'type': 'custom_tool_call', 'id': f'ctc_{n}', 'call_id': f'call_{n}',
                    'name': name, 'input': arguments}
        return {'id': f'response_{n}', 'object': 'response', 'status': 'completed', 'error': None, 'output': [item]}


class Capture:
    """Records wire shapes only; this is NOT JV server acceptance."""
    def __init__(self, delegate=None, inspect_path=None):
        self.delegate = delegate
        self.inspect_path = inspect_path
        self.requests = []

    def begin_turn(self):
        if self.delegate:
            self.delegate.begin_turn()

    def infer(self, request, runtime):
        self.requests.append(request)
        if self.delegate:
            return self.delegate.infer(request, runtime)
        if len(self.requests) == 1:
            return [{'type': 'function_call', 'id': 'fc_capture', 'call_id': 'call_capture',
                     'status': 'completed', 'name': 'view_image',
                     'arguments': json.dumps({'path': str(self.inspect_path)})}]
        return [{'type': 'message', 'id': 'msg_capture', 'role': 'assistant', 'status': 'completed',
                 'content': [{'type': 'output_text', 'text': 'PARITY_SCRIPT_OK', 'annotations': []}]}]


def run(engine, folder, processor, client, *, images=(), thread=None):
    runtime = AdapterRuntime(client, processor=processor)
    out, err = io.StringIO(), io.StringIO()
    try:
        port = runtime.start()
        overrides = cli._write_engine_config(folder, port, structured=True, allow_network=True)
        runtime.begin_turn()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc, thread = cli._run_engine(engine, 'Complete the scripted local fixture check.', thread,
                session_dir=folder, overrides=overrides, runtime=runtime, images=images, turn_timeout=90)
        if rc or out.getvalue().strip() != 'PARITY_SCRIPT_OK':
            raise JvError(f'Pinned engine check failed: {runtime.last_error or err.getvalue()[-1500:]}')
        assert runtime.response_repairs == 0
        return thread
    finally:
        runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', help='Existing Chrome executable for optional sandboxed screenshot capture')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise JvError('Run as a normal user; sandbox bypass is not supported')
    engine = cli._find_engine()
    if not engine or cli._version_of_engine(engine) != '0.149.1':
        raise JvError('Exact pinned engine 0.149.1 is required')
    folder = private_dir(cli.STATE_DIR / 'parity-checks' / uuid.uuid4().hex)
    workspace = private_dir(folder / 'workspace')
    checks = {}
    report = {'engine': '0.149.1', 'live_api': False, 'fixture': str(folder), 'checks': checks}
    old = Path.cwd()
    try:
        os.chdir(workspace)
        (workspace / 'index.html').write_text('<!doctype html><link rel="stylesheet" href="style.css"><h1>Fixture</h1><script src="app.js"></script>')
        (workspace / 'style.css').write_text('h1 { color: white; background: white; }\n')
        (workspace / 'app.js').write_text('console.log("web fixture");\n')
        (workspace / 'package.json').write_text(json.dumps({'name': 'jv-disposable-web', 'private': True,
            'scripts': {'test': 'node test.js', 'build': 'node --check app.js'}}))
        (workspace / 'test.js').write_text('const fs = require("fs"); if (!fs.readFileSync("style.css", "utf8").includes("color: black")) process.exit(1); console.log("WEB_TEST_OK");\n')
        session = private_dir(folder / 'web-session')
        client = Script([
            ('update_plan', {'plan': [{'step': 'Read and correct the fixture', 'status': 'in_progress'}]}, None),
            ('shell_command', {'command': 'ls && cat index.html style.css app.js package.json'}, None),
            ('shell_command', {'command': "python3 -c 'from pathlib import Path; p=Path(\"style.css\"); p.write_text(p.read_text().replace(\"color: white\", \"color: black\"))' && npm run build && npm test"}, '<!doctype html>'),
            (None, None, 'WEB_TEST_OK'),
        ])
        capture = Capture(StructuredProcessor(client, session / 'structured'))
        run(engine, session, capture, client)
        assert 'color: black' in (workspace / 'style.css').read_text()
        assert all(not any(p.get('type') == 'input_file' for m in body['input'] for p in m.get('content', []) if isinstance(p, dict)) for body, _ in client.posts)
        checks['web_read_edit_build_test_no_uploads'] = True
        checks['update_plan_and_three_serial_continuations'] = True
        catalog = capture.requests[0]['tools']
        report['tool_catalog'] = [{'type': t['type'], 'name': t.get('name'),
            **({'members': [x['name'] for x in t['tools']]} if t['type'] == 'namespace' else {})} for t in catalog]
        (workspace / 'image.png').write_bytes(tiny_png())
        session = private_dir(folder / 'image-session')
        client = Script([('shell_command', {'command': 'printf IMAGE_SHELL_OK'}, None), (None, None, 'IMAGE_SHELL_OK')])
        capture = Capture(StructuredProcessor(client, session / 'structured'))
        images = snapshot_images(['image.png'], workspace, session / 'images')
        thread = run(engine, session, capture, client, images=images)
        sent = [p for m in client.posts[0][0]['input'] for p in m.get('content', []) if isinstance(p, dict) and p.get('type') == 'input_image']
        assert len(sent) == 1 and sent[0]['detail'] == 'high'
        assert base64.b64decode(sent[0]['image_url'].split(',')[1]) == tiny_png()
        assert client.posts[1][0]['input'][0]['type'] == 'function_call_output'
        checks['local_image_actual_bytes_and_attachment_continuation'] = True
        # A new process reads both Codex rollout history and durable JV state.
        resumed = Script([(None, None, None)])
        # Distinct IDs are required for a fresh round in the same journal.
        original_create = resumed.create_response
        def resume_response(body, key):
            reply = original_create(body, key)
            reply['id'] = 'response_resume'; reply['output'][0]['id'] = 'msg_resume'
            return reply
        resumed.create_response = resume_response
        run(engine, session, Capture(StructuredProcessor(resumed, session / 'structured')), resumed, thread=thread)
        checks['structured_resume_with_image_history'] = True
        # Execute through the real structured processor, not the capture-only bypass.
        session = private_dir(folder / 'view-capture-session')
        view_client = Script([('view_image', {'path': str(workspace / 'image.png')}, None), (None, None, None)])
        capture = Capture(StructuredProcessor(view_client, session / 'structured'))
        run(engine, session, capture, view_client)
        results = [x for x in capture.requests[-1]['input'] if x.get('type') == 'function_call_output']
        assert results and isinstance(results[-1]['output'], list)
        assert results[-1]['output'][0]['type'] == 'input_image'
        assert base64.b64decode(results[-1]['output'][0]['image_url'].split(',')[1]) == tiny_png()
        assert view_client.posts[1][0]['input'][0]['output'] == results[-1]['output']
        checks['view_image_structured_continuation'] = True
        patch_session = private_dir(folder / 'patch-session')
        patch = '*** Begin Patch\n*** Add File: patched.txt\n+exact local patch\n*** End Patch\n'
        patch_client = Script([('apply_patch', patch, None), ('shell_command', {'command': 'cat patched.txt'}, 'Success'),
                               (None, None, 'exact local patch')])
        patch_capture = Capture(StructuredProcessor(patch_client, patch_session / 'structured'))
        patch_thread = run(engine, patch_session, patch_capture, patch_client)
        assert (workspace / 'patched.txt').read_text() == 'exact local patch\n'
        assert patch_client.posts[1][0]['input'][0]['type'] == 'custom_tool_call_output'
        checks['custom_apply_patch_local_execution_and_serial_results'] = True
        resumed_patch = Script([(None, None, None)])
        original_patch_create = resumed_patch.create_response
        def patch_resume_response(body, key):
            reply = original_patch_create(body, key)
            reply['id'] = 'response_patch_resume'; reply['output'][0]['id'] = 'msg_patch_resume'
            return reply
        resumed_patch.create_response = patch_resume_response
        run(engine, patch_session, Capture(StructuredProcessor(resumed_patch, patch_session / 'structured')),
            resumed_patch, thread=patch_thread)
        checks['resume_after_custom_patch'] = True
        report['view_image_shape'] = {'type': 'function_call_output', 'call_id': 'call_capture',
            'output': [{'type': 'input_image', 'image_url': '<actual PNG data URL omitted>', 'detail': 'high'}]}
        if args.browser:
            # Keep Chrome's Unix socket paths below the OS length limit, while
            # retaining all profile/temp files inside private JV CLI state.
            browser_root = private_dir(cli.STATE_DIR / 'b' / uuid.uuid4().hex[:6])
            browser_workspace = private_dir(browser_root / 'w')
            browser_session = private_dir(browser_root / 's')
            page = browser_workspace / 'index.html'
            prepare_web(browser_workspace, browser_session, args.browser)
            screenshot = browser_workspace / 'screenshot.png'
            command = ' '.join(shlex.quote(x) for x in [args.browser, '--headless', '--disable-gpu',
                '--no-first-run', '--no-default-browser-check', '--disable-dev-shm-usage', '--timeout=5000',
                '--user-data-dir=' + str(browser_session / 'tool-home/browser-profile'),
                '--screenshot=' + str(screenshot), '--window-size=800,600', page.as_uri()])
            command += ' && test -s screenshot.png && printf SCREENSHOT_OK'
            os.chdir(browser_workspace)
            browser_client = Script([('shell_command', {'command': command}, None), (None, None, 'SCREENSHOT_OK')])
            run(engine, browser_session, Capture(StructuredProcessor(browser_client,
                browser_session / 'structured')), browser_client)
            view_session = private_dir(browser_root / 'v')
            css = (browser_workspace / 'style.css').read_text().splitlines()[-1]
            browser_patch = ('*** Begin Patch\n*** Update File: style.css\n@@\n-' + css + '\n+'
                             + css.replace('width: 420px;', 'width: 100%; box-sizing: border-box;') + '\n*** End Patch\n')
            view_client = Script([('view_image', {'path': str(screenshot)}, None),
                ('apply_patch', browser_patch, None),
                ('shell_command', {'command': 'npm run build && npm test'}, 'Success'),
                (None, None, 'UI_TEST_OK')])
            view_capture = Capture(StructuredProcessor(view_client, view_session / 'structured'))
            run(engine, view_session, view_capture, view_client)
            result = [x for x in view_capture.requests[1]['input'] if x.get('type') == 'function_call_output'][-1]
            assert result['output'][0]['type'] == 'input_image'
            assert base64.b64decode(result['output'][0]['image_url'].split(',')[1]) == screenshot.read_bytes()
            assert view_client.posts[1][0]['input'][0]['output'] == result['output']
            checks['browser_screenshot_view_image_patch_correction'] = True
            report['browser_fixture'] = str(browser_root)
        report['limitations'] = ['Scripted provider does not prove visual reasoning.',
            'No production authentication or inference performed.']
    finally:
        os.chdir(old)
        (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (JvError, AssertionError) as exc:
        print('Parity check failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
