#!/usr/bin/env python3
"""Bounded production core checks with the pinned engine and hidden terminal login.

Run only after offline validation. Creates disposable state/workspaces, uses four
small scenarios (at most 22 total rounds), and never automatically reruns a case.
The report contains safe validation metadata, not prompts, image data or replies.
"""
from __future__ import annotations
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shlex
import struct
import subprocess
import sys
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.images import snapshot_images
from jvcli.safety import JvError, atomic_write, private_dir, redact
from jvcli.structured import StructuredProcessor
from jvcli.transport import JvApiClient, JvClientConfig


def color_png(rgb):
    def chunk(t, data):
        return struct.pack('>I', len(data)) + t + data + struct.pack('>I', zlib.crc32(t + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 128, 128, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes(rgb) * 128) * 128)) + chunk(b'IEND', b''))


def response_text(rounds):
    item = rounds[-1].get('output', {}) if rounds else {}
    return item.get('content', [{}])[0].get('text', '') if item.get('type') == 'message' else ''


def calls(rounds, name):
    return [r for r in rounds if r.get('output', {}).get('name') == name]


def result_for(rounds, call):
    return next(r['body']['input'][0] for r in rounds
                if r.get('parent_call_id') == call['output']['call_id'])


def execute(client, engine, session, workspace, prompt, *, images=(), max_rounds=6):
    processor = StructuredProcessor(client, session / 'structured')
    runtime = AdapterRuntime(client, max_requests=max_rounds, processor=processor)
    out, err = io.StringIO(), io.StringIO()
    old = Path.cwd()
    try:
        os.chdir(workspace)
        port = runtime.start()
        overrides = cli._write_engine_config(session, port, structured=True, allow_network=True)
        runtime.begin_turn()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc, thread = cli._run_engine(engine, prompt, None, session_dir=session,
                overrides=overrides, runtime=runtime, images=images, turn_timeout=900)
        if rc:
            raise JvError(runtime.last_error or 'Pinned engine did not complete the live scenario')
        rounds = processor.state.rounds
        if runtime.response_repairs or not rounds or rounds[-1]['phase'] != 'final':
            raise JvError('Live scenario did not complete with zero repairs')
        keys = [r['key'] for r in rounds]
        if len(set(keys)) != len(keys): raise JvError('Duplicate logical-round key')
        for index, item in enumerate(rounds):
            if not item.get('parent_call_id'): continue
            prior = rounds[index - 1]
            if (item['body'].get('previous_response_id') != prior['response_id']
                    or item['body']['input'][0]['call_id'] != prior['output']['call_id']
                    or item['body']['input'][0]['type'] != prior['output']['type'] + '_output'):
                raise JvError('Live continuation identity mismatch')
        # Check only known bearer/key bytes; do not print any matching payload.
        for file in session.rglob('*.json'):
            data = file.read_bytes()
            if any(secret and secret.encode() in data for secret in (client._token, runtime.key)):
                raise JvError('Credential unexpectedly persisted in session JSON')
        return rounds
    finally:
        runtime.close()
        os.chdir(old)


def prepare_web(workspace, session, browser):
    (workspace / 'index.html').write_text('<!doctype html><link rel="stylesheet" href="style.css"><main><h1>Checkout</h1><button>Continue</button></main><script src="app.js"></script>\n')
    (workspace / 'style.css').write_text('body { font-family: sans-serif; padding: 30px; }\nmain { width: 260px; padding: 16px; border: 3px solid #222; }\nbutton { width: 420px; background: #1264d8; color: white; padding: 20px; border: 0; }\n')
    app = ('document.querySelector("button").onclick = () => { document.querySelector("h1").textContent = "Thanks"; };\n'
           'window.onload = () => { const b=document.querySelector("button"), m=document.querySelector("main"); '
           'document.documentElement.dataset.uiOverflow=String(b.getBoundingClientRect().right > m.getBoundingClientRect().right); '
           'if(location.hash === "#verify") { b.click(); document.documentElement.dataset.interactionOk=String(document.querySelector("h1").textContent === "Thanks"); } };\n')
    (workspace / 'app.js').write_text(app)
    (workspace / 'package.json').write_text(json.dumps({'name': 'jv-core-live-fixture', 'private': True,
        'scripts': {'build': 'node --check app.js', 'test': 'node test.js', 'screenshot': 'sh render.sh'}}))
    browser_args = ['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
        '--disable-dev-shm-usage', '--dump-dom', '--virtual-time-budget=2000',
        '--user-data-dir=' + str(session / 'tool-home/test-browser'), (workspace / 'index.html').as_uri() + '#verify']
    test = ('const cp=require("child_process");const html=cp.execFileSync(' + json.dumps(browser) + ','
            + json.dumps(browser_args) + ',{encoding:"utf8",timeout:15000,stdio:["ignore","pipe","ignore"]});'
            "if(!html.includes('data-ui-overflow=\"false\"') || !html.includes('data-interaction-ok=\"true\"')) process.exit(1);"
            'console.log("UI_TEST_OK");\n')
    (workspace / 'test.js').write_text(test)
    render = ' '.join(shlex.quote(x) for x in [browser, '--headless', '--disable-gpu', '--no-first-run',
        '--no-default-browser-check', '--disable-dev-shm-usage', '--timeout=5000',
        '--user-data-dir=' + str(session / 'tool-home/browser-profile'),
        '--screenshot=' + str(workspace / 'screenshot.png'), '--window-size=800,600',
        (workspace / 'index.html').as_uri()])
    (workspace / 'render.sh').write_text('#!/bin/sh\nset -eu\n' + render + '\n')
    return app, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True, help='New private directory beneath repository state')
    parser.add_argument('--browser', default='/usr/bin/google-chrome')
    args = parser.parse_args()
    if os.geteuid() == 0 or not sys.stdin.isatty():
        raise JvError('A normal-user terminal is required for hidden password input')
    root = args.fixture.absolute()
    if not root.is_relative_to(cli.STATE_DIR.resolve()) or root.exists():
        raise JvError('Use a new fixture directory beneath JV CLI state; existing runs are never overwritten')
    private_dir(root)
    report = {'contract': '52be8980e01828959df7712ddae17d077d69efcf', 'engine': '0.149.1',
              'status': 'awaiting_hidden_login', 'checks': {}, 'model_rounds': 0}
    report_path = root / 'report.json'
    def save(): atomic_write(report_path, json.dumps(report, indent=2) + '\n')
    def accepted(name, rounds):
        report['checks'][name] = {'passed': True, 'rounds': len(rounds), 'prompt_repairs': 0,
            'response_ids': [r['response_id'] for r in rounds],
            'tool_names': [r['output']['name'] for r in rounds if 'name' in r.get('output', {})]}
        report['model_rounds'] += len(rounds)
        save()
        print(name + ': PASS', flush=True)
    save()
    engine = cli._find_engine()
    if not engine or cli._version_of_engine(engine) != '0.149.1': raise JvError('Pinned 0.149.1 engine required')
    print('JV production core acceptance: four bounded disposable scenarios. No automatic case retries.')
    print('Enter credentials only in this terminal; the password will be hidden.')
    username = input('JV LLM username: ').strip()
    # Always use hidden terminal entry for this operator-driven test.
    os.environ.pop('JV_API_PASSWORD', None)
    client = JvApiClient(JvClientConfig(base_url='https://ai.openjvspace.com', request_timeout=30,
        wait_timeout=300, poll_interval=3, temp_dir=private_dir(root / 'tmp')))
    stage = 'authentication'
    try:
        password = cli._password()
        try: client.login(username, password)
        finally: del password
        report['status'] = 'running'; save()
        colors = [('red', (230, 20, 20)), ('blue', (15, 50, 230)), ('green', (10, 190, 30)), ('yellow', (245, 220, 10))]
        stage = 'initial_image'
        workspace = private_dir(root / 'i'); session = private_dir(root / 'is')
        expected, rgb = secrets.choice(colors)
        data = color_png(rgb); (workspace / 'visual.png').write_bytes(data)
        snapshots = snapshot_images(['visual.png'], workspace, session / 'images')
        rounds = execute(client, engine, session, workspace,
            'Look at the attached image directly. What is its dominant color? Reply with only the English color name. Do not use tools.',
            images=snapshots, max_rounds=2)
        parts = [p for m in rounds[0]['body']['input'] for p in m.get('content', [])
                 if isinstance(p, dict) and p.get('type') == 'input_image']
        if (len(rounds) != 1 or expected not in response_text(rounds).lower() or len(parts) != 1
                or base64.b64decode(parts[0]['image_url'].split(',')[1]) != data):
            raise JvError('Initial-image hidden visual fact or exact-byte validation failed')
        accepted(stage, rounds)
        stage = 'view_image'
        workspace = private_dir(root / 'v'); session = private_dir(root / 'vs')
        expected, rgb = secrets.choice(colors)
        data = color_png(rgb); (workspace / 'visual.png').write_bytes(data)
        rounds = execute(client, engine, session, workspace,
            'Use view_image on visual.png exactly once. From the actual image, report only its dominant color in English. Do not use shell or any other tool.', max_rounds=3)
        views = calls(rounds, 'view_image')
        if len(views) != 1 or len(rounds) != 2 or expected not in response_text(rounds).lower():
            raise JvError('view_image hidden visual fact validation failed')
        result = result_for(rounds, views[0])['output']
        if not isinstance(result, list) or base64.b64decode(result[0]['image_url'].split(',')[1]) != data:
            raise JvError('view_image exact image bytes were not preserved')
        accepted(stage, rounds)
        stage = 'apply_patch'
        workspace = private_dir(root / 'p'); session = private_dir(root / 'ps')
        marker = 'LOCAL_PATCH_' + secrets.token_hex(5)
        rounds = execute(client, engine, session, workspace,
            'Use the custom apply_patch tool to create proof.txt containing exactly ' + marker +
            ' followed by a newline. Then use shell_command to cat proof.txt and report that exact observed token. Do not write the file through shell.', max_rounds=5)
        patches = calls(rounds, 'apply_patch')
        if (not patches or not calls(rounds, 'shell_command')
                or (workspace / 'proof.txt').read_text() != marker + '\n'
                or marker not in response_text(rounds)
                or any(result_for(rounds, p)['type'] != 'custom_tool_call_output' for p in patches)):
            raise JvError('Local custom patch/execution/result validation failed')
        accepted(stage, rounds)
        stage = 'web_ui'
        workspace = private_dir(root / 'w'); session = private_dir(root / 's')
        app, test = prepare_web(workspace, session, args.browser)
        rounds = execute(client, engine, session, workspace,
            'Inspect this disposable web project using local tools. Run npm run build and npm run screenshot. '
            'Use view_image on screenshot.png before changing CSS. Identify the visible layout issue from the screenshot. '
            'Correct it using custom apply_patch on style.css, preserve the button interaction, then run npm run build and npm test. '
            'Do not change test.js or render.sh, do not install packages. Finish by describing the observed visual issue and verification.', max_rounds=12)
        views, patches, shells = calls(rounds, 'view_image'), calls(rounds, 'apply_patch'), calls(rounds, 'shell_command')
        if not views or not patches or not shells or rounds.index(views[0]) >= rounds.index(patches[0]):
            raise JvError('Web loop did not inspect image before local custom correction')
        if (workspace / 'test.js').read_text() != test or (workspace / 'app.js').read_text() != app:
            raise JvError('Fixture test or measured interaction was changed')
        visual_words = ('overflow', 'wider', 'outside', 'exceed', 'extend', 'wide', 'overhang', 'spill')
        if not any(word in response_text(rounds).lower() for word in visual_words):
            raise JvError('Final web answer did not identify the visible layout issue')
        outputs = [result_for(rounds, call)['output'] for call in shells]
        if not any(isinstance(out, str) and 'UI_TEST_OK' in out and 'Exit code: 0' in out for out in outputs):
            raise JvError('Codex did not return an actual passing local test result')
        screenshot_bytes = (workspace / 'screenshot.png').read_bytes()
        if base64.b64decode(result_for(rounds, views[0])['output'][0]['image_url'].split(',')[1]) != screenshot_bytes:
            raise JvError('Web screenshot bytes changed before image verification')
        accepted(stage, rounds)
        report['status'] = 'passed'; save()
        print('All four bounded live core scenarios passed.', flush=True)
        return 0
    except (JvError, OSError, KeyboardInterrupt, StopIteration, ValueError) as exc:
        report['status'] = 'failed'; report['failed_stage'] = stage
        report['error'] = redact(str(exc), (client._token or '',))[:500]
        save()
        print('Stopped at ' + stage + '; no automatic scenario retry. Inspect the private safe report.', flush=True)
        return 1
    finally:
        cli._logout(client)


if __name__ == '__main__':
    raise SystemExit(main())
