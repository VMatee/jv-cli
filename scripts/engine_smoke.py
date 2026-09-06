#!/usr/bin/env python3
"""Use the REAL locally installed engine against scripted model responses.

No JV account or live LLM request is used. Test model traffic stays on loopback.
Creates a disposable fixture under the installation's .state/engine-checks.
This script must pass on the target Ubuntu host before distributing to users.
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.safety import JvError, atomic_write, private_dir
from jvcli.transport import JvClientConfig


class ScriptedClient:
    _token = None
    base_url = 'http://127.0.0.1'
    def __init__(self, steps):
        self.steps = list(steps)
        self.config = JvClientConfig(request_timeout=1, wait_timeout=5, poll_interval=.01)
        self.pending = {}
        self.count = 0
    def submit_job(self, prompt):
        if not self.steps:
            raise JvError('Engine requested an unexpected extra model call')
        answer, required = self.steps.pop(0)
        if required and (('[tool result ' not in prompt) or required not in prompt.rsplit('[tool result ', 1)[1]):
            raise JvError('Actual tool output was not returned in the next model request')
        self.count += 1
        key = f'job_check_{self.count}'
        self.pending[key] = answer if isinstance(answer, str) else json.dumps(answer)
        return {'id': key, 'conversation_id': f'conv_check_{self.count}', 'status': 'queued'}
    def wait_for_job(self, key, **kwargs):
        return {'id': key, 'conversation_id': kwargs.get('conversation_id'), 'status': 'succeeded',
                'answer': self.pending[key], 'response': {'files': []}}


def run_case(engine, folder, name, steps, *, thread_id=None, read_only=False,
             repairs=0, expected_error=None, expected_output=None, allow_network=False):
    client = ScriptedClient(steps)
    runtime = AdapterRuntime(client, heartbeat=.5)
    output, errors = io.StringIO(), io.StringIO()
    try:
        port = runtime.start()
        overrides = cli._write_engine_config(folder, port, read_only=read_only, allow_network=allow_network)
        runtime.begin_turn()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            rc, thread = cli._run_engine(engine, f'Run the local acceptance case: {name}', thread_id,
                session_dir=folder, overrides=overrides, runtime=runtime, turn_timeout=90)
        success = rc == 0 if expected_error is None else (
            rc != 0 and expected_error in (runtime.last_error or '') and
            expected_error in errors.getvalue())
        if not success or client.steps or runtime.response_repairs != repairs:
            raise JvError(f'{name} failed (exit {rc}):\n{errors.getvalue()[-5000:]}\n{output.getvalue()[-1000:]}')
        if expected_output is not None and output.getvalue().strip() != expected_output:
            raise JvError(f'{name}: final text did not match the decoded envelope')
        return thread
    finally:
        runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', help='Explicit path to the pinned real Codex engine')
    parser.add_argument('--flask-python', help='Optional Python with Flask already installed; test a disposable generated Flask app without installing packages')
    args = parser.parse_args()
    if os.geteuid() == 0:
        print('Run the real-engine acceptance test as your normal Ubuntu user, not root.', file=sys.stderr)
        return 1
    engine = args.engine or cli._find_engine()
    if not engine:
        print('Engine missing. Run ./install.sh first.', file=sys.stderr)
        return 1
    checks = {}
    report_dir = private_dir(cli.STATE_DIR / 'engine-checks' / uuid.uuid4().hex)
    old_cwd = Path.cwd()
    report = {'real_engine': str(engine), 'live_jv_api_used': False, 'checks': checks, 'fixture': str(report_dir)}
    try:
        if cli._version_of_engine(engine) != cli.ENGINE_VERSION:
            raise JvError('The real engine is not the pinned version')
        workspace = private_dir(report_dir / 'workspace')
        session = private_dir(report_dir / 'session')
        protected = report_dir / 'outside-workspace.txt'
        protected.write_text('DO NOT CHANGE')
        marker = 'actual-file-data-' + uuid.uuid4().hex
        (workspace / 'smoke.txt').write_text(marker)
        os.chdir(workspace)
        thread = run_case(engine, session, 'read an actual file', [
            ({'type':'tool_call','name':'shell_command','arguments':{'command':'cat smoke.txt'}},None),
            ({'type':'final','text':'READ_OK'},marker)])
        checks['real_shell_execution_and_tool_result'] = True
        patch = '*** Begin Patch\n*** Add File: generated.txt\n+PATCH_OK\n*** End Patch'
        thread = run_case(engine, session, 'resume and apply a patch', [
            ({'type':'custom_tool_call','name':'apply_patch','input':patch},None),
            ({'type':'final','text':'PATCH_OK'},None)], thread_id=thread)
        if not (workspace / 'generated.txt').is_file() or (workspace / 'generated.txt').read_text().strip() != 'PATCH_OK':
            raise JvError('The custom apply_patch tool did not create the expected file')
        checks['real_resume_and_custom_apply_patch'] = True
        def labeled(value):
            return 'JSON\n\n```\n' + json.dumps(value) + '\n```'
        framed_patch = '*** Begin Patch\n*** Add File: framed.py\n+value = "__literal__"\n*** End Patch'
        thread = run_case(engine, session, 'labeled JSON patch and tool result', [
            (labeled({'type':'custom_tool_call','name':'apply_patch','input':framed_patch}), None),
            (labeled({'type':'tool_call','name':'shell_command','arguments':{
                'command': "python3 -B -c 'from framed import value; print(value)'"} }), None),
            (labeled({'type':'final','text':'FRAMED_PATCH_OK'}), '__literal__')
        ], thread_id=thread)
        if (workspace / 'framed.py').read_text() != 'value = "__literal__"\n':
            raise JvError('The labeled code block did not preserve patch contents')
        checks['labeled_json_patch_and_tool_result'] = True
        nested_example = 'Example only:\n```rust\nfn main() {}\n```'
        run_case(engine, session, 'four-backtick final with nested code example', [
            ('JSON\n\n````json\n' + json.dumps({'type': 'final', 'text': nested_example})
             + '\n````', None)], expected_output=nested_example)
        checks['long_fence_final_decoded_without_raw_json'] = True
        # Function definitions make discovery deterministic and install nothing.
        # No filesystem-wide search or external project toolchain is used.
        probes = [
            ({'type': 'tool_call', 'name': 'shell_command', 'arguments': {
                'command': 'cargo() { return 127; }; cargo --version; '
                           f'printf "PROBE_{index}"'}}, None)
            for index in range(6)]
        probes.append(({'type': 'tool_calls', 'calls': [
            {'type': 'tool_call', 'name': 'shell_command', 'arguments': {
                'command': 'touch discovery-must-not-run.txt'}},
            {'type': 'tool_call', 'name': 'shell_command', 'arguments': {
                'command': 'command -v cargo'}}]}, 'PROBE_5'))
        run_case(engine, session, 'stop varied discovery without partial batch execution',
                 probes, expected_error='Rust prerequisite discovery limit')
        if (workspace / 'discovery-must-not-run.txt').exists():
            raise JvError('SAFETY FAILURE: discovery-limit rejection executed part of a batch')
        checks['discovery_loop_bounded_without_partial_execution'] = True
        malformed_patch = '{"type":"custom_tool_call","name":"apply_patch","input":"*** Begin Patch'
        thread = run_case(engine, session, 'recover a malformed patch after a successful tool', [
            ({'type':'tool_call','name':'shell_command','arguments':{'command':'cat smoke.txt'}}, None),
            (malformed_patch, marker),
            ({'type':'custom_tool_call','name':'apply_patch','input_lines':[
                '*** Begin Patch', '*** Add File: recovered.txt', '+RECOVERED_PATCH_OK',
                '*** End Patch']}, marker),
            ({'type':'tool_call','name':'shell_command','arguments':{'command':'cat recovered.txt'}}, None),
            ({'type':'final','text':'RECOVERY_OK'}, 'RECOVERED_PATCH_OK')
        ], thread_id=thread, repairs=1)
        if (workspace / 'recovered.txt').read_text().strip() != 'RECOVERED_PATCH_OK':
            raise JvError('Response correction did not produce the expected patch')
        checks['malformed_response_recovery_and_tool_result'] = True
        run_case(engine, session, 'recover a generic provider error', [
            ("I'm having a hard time fulfilling your request. Can I help you with something else instead?", None),
            ({'type':'tool_call','name':'shell_command','arguments':{'command':'cat smoke.txt'}}, None),
            ({'type':'final','text':'PROVIDER_RECOVERY_OK'}, marker)
        ], repairs=1)
        checks['generic_provider_error_recovery'] = True
        # Even the valid member of a rejected batch must never execute.
        invalid_batch = {'type':'tool_calls','calls':[
            {'type':'tool_call','name':'shell_command','arguments':{'command':'touch must-not-exist.txt'}},
            {'type':'tool_call','name':'unoffered_tool','arguments':{}}]}
        run_case(engine, session, 'stop repeated invalid responses without executing tools',
                 [(invalid_batch, None)] * 3, repairs=2,
                 expected_error='Response correction stopped after 2 extra model jobs')
        if (workspace / 'must-not-exist.txt').exists():
            raise JvError('SAFETY FAILURE: a rejected tool batch was partially executed')
        checks['repeated_invalid_response_fails_without_execution'] = True
        if args.flask_python:
            # Do not resolve a venv's python symlink: its directory selects the
            # virtual environment even when the binary points outside it.
            flask_python = str(Path(args.flask_python).absolute())
            if not Path(flask_python).is_file():
                raise JvError('The requested Flask Python executable does not exist')
            files = {
                'app.py': 'from flask import Flask, render_template\napp = Flask(__name__)\n@app.get("/")\ndef index():\n    return render_template("index.html")\n',
                'templates/index.html': '<!doctype html><html lang="en"><head><title>Thailand</title><link rel="stylesheet" href="/static/style.css"></head><body><h1>I love Thailand</h1></body></html>\n',
                'static/style.css': 'h1 { animation: pulse 2s ease-in-out infinite; }\n@keyframes pulse { 50% { transform: scale(1.05); } }\n@media (prefers-reduced-motion: reduce) { h1 { animation: none; } }\n',
                'requirements.txt': 'Flask>=3,<4\n',
            }
            lines = ['*** Begin Patch']
            for name, content in files.items():
                lines += ['*** Add File: ' + name] + ['+' + line for line in content.splitlines()]
            lines.append('*** End Patch')
            code = ('from app import app; client = app.test_client(); response = client.get("/"); '
                    'assert response.status_code == 200; assert b"I love Thailand" in response.data; '
                    'css = client.get("/static/style.css"); assert css.status_code == 200; '
                    'assert b"@keyframes" in css.data; print("FLASK_HTTP_AND_ANIMATION_OK")')
            run_case(engine, session, 'generate and exercise a Flask app after malformed output', [
                (malformed_patch, None),
                ({'type':'custom_tool_call','name':'apply_patch','input_lines':lines}, None),
                ({'type':'tool_call','name':'shell_command','arguments':{
                    'command': shlex.quote(flask_python) + ' -B -c ' + shlex.quote(code)}}, None),
                ({'type':'final','text':'FLASK_CHECK_DONE'}, 'FLASK_HTTP_AND_ANIMATION_OK')
            ], repairs=1)
            for name, content in files.items():
                if (workspace / name).read_text() != content:
                    raise JvError('Flask fixture contents did not match the validated patch')
            checks['flask_app_creation_and_test_client_after_recovery'] = True
        run_case(engine, session, 'sandbox outside-workspace write denial', [
            ({'type':'tool_call','name':'shell_command','arguments':{'command':'printf JV_WRITE_ATTEMPT; printf changed > ' + shlex.quote(str(protected))}},None),
            ({'type':'final','text':'DENIAL_CHECK_DONE'},'JV_WRITE_ATTEMPT')], thread_id=thread)
        if protected.read_text() != 'DO NOT CHANGE':
            raise JvError('SAFETY FAILURE: the engine changed a file outside the allowed workspace')
        checks['outside_workspace_write_denied'] = True
        run_case(engine, session, 'read-only write denial', [
            ({'type':'tool_call','name':'shell_command','arguments':{'command':'printf JV_READONLY_ATTEMPT; printf forbidden > readonly-must-not-exist.txt'}},None),
            ({'type':'final','text':'READ_ONLY_CHECK_DONE'},'JV_READONLY_ATTEMPT')], read_only=True)
        if (workspace / 'readonly-must-not-exist.txt').exists():
            raise JvError('SAFETY FAILURE: read-only mode allowed a write')
        checks['read_only_write_denied'] = True
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                hits.append(True)
                self.send_response(200); self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok')
        http = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker = threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        try:
            code=f"import urllib.request; print('JV_NETWORK_ATTEMPT', flush=True); urllib.request.urlopen('http://127.0.0.1:{http.server_address[1]}/', timeout=2).read()"
            run_case(engine, session, 'tool networking disabled', [
                ({'type':'tool_call','name':'shell_command','arguments':{'command':'python3 -c ' + shlex.quote(code)}},None),
                ({'type':'final','text':'NETWORK_CHECK_DONE'},'JV_NETWORK_ATTEMPT')])
            if hits:
                raise JvError('SAFETY FAILURE: tool reached a network endpoint with networking disabled')
            checks['tool_network_denied'] = True
            code = (f"import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:{http.server_address[1]}/', timeout=2); "
                    "assert response.read() == b'ok'; print('JV_NETWORK_ALLOWED')")
            run_case(engine, session, 'tool networking explicitly enabled', [
                ({'type':'tool_call','name':'shell_command','arguments':{'command':'python3 -c ' + shlex.quote(code)}}, None),
                ({'type':'final','text':'NETWORK_ALLOW_CHECK_DONE'}, 'JV_NETWORK_ALLOWED')], allow_network=True)
            if not hits:
                raise JvError('Enabled tool networking did not reach the local fixture server')
            checks['tool_network_allowed'] = True
            run_case(engine, session, 'network access does not grant outside-workspace writes', [
                ({'type':'tool_call','name':'shell_command','arguments':{
                    'command':'printf JV_NETWORK_WRITE_ATTEMPT; printf changed > ' + shlex.quote(str(protected))}}, None),
                ({'type':'final','text':'NETWORK_WRITE_DENIED'}, 'JV_NETWORK_WRITE_ATTEMPT')], allow_network=True)
            if protected.read_text() != 'DO NOT CHANGE':
                raise JvError('SAFETY FAILURE: network-enabled mode allowed outside-workspace writes')
            checks['network_enabled_outside_workspace_write_denied'] = True
        finally:
            http.shutdown();http.server_close();worker.join(1)
        report['ok'] = True
    except (JvError,OSError) as exc:
        report['ok'] = False
        report['error'] = str(exc)
    finally:
        os.chdir(old_cwd)
        atomic_write(report_dir / 'report.json', json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print(f'Report saved: {report_dir / "report.json"}', file=sys.stderr)
    return 0 if report['ok'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
