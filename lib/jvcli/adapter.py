"""Authenticated loopback Responses bridge. No local tools execute here."""
from __future__ import annotations

import hashlib
import json
import queue
import secrets
import shlex
import socket
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .safety import Cancelled, JvError, ProtocolError, SubmissionUncertain, strict_json
from .transport import DEFAULT_BASE_URL, MAX_JSON_BYTES, JvApiClient, JvClientConfig, validate_base_url
from .protocol import (MAX_PROMPT_BYTES, build_jv_prompt, flatten_tools, parse_agent_output,
                       render_input_item, sanitize_internal_text, MAX_RESPONSE_REPAIRS,
                       provider_failure, response_repair_prompt)

MAX_RUST_DISCOVERY_PROBES = 6


def rust_discovery_probe(command: str) -> bool:
    """Recognize common discovery loops, not a shell security boundary.

    Never rewrite/execute shell text. Build, run, check and source edits do not
    count. Quoted scripts/heredocs are deliberately not recursively interpreted.
    """
    if '<<' in command:
        return False
    try:
        lexer = shlex.shlex(command.replace('\n', ' ; '), posix=True,
                            punctuation_chars=';&|()')
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    segments = [[]]
    for token in tokens:
        if token and all(char in ';&|()' for char in token):
            segments.append([])
        else:
            segments[-1].append(token)
    names = {'cargo', 'rustc', 'rustup'}
    for words in segments:
        while words and '=' in words[0] and not words[0].startswith('-'):
            words = words[1:]
        if not words:
            continue
        head, args = words[0], words[1:]
        if head in ('which', 'type') or (head == 'command' and '-v' in args):
            if names.intersection(args):
                return True
        if head in names and any(arg in ('--version', '-V') for arg in args):
            return True
        if head == 'rustup' and (args[:1] == ['show'] or args[:2] == ['toolchain', 'list']):
            return True
        if head == 'find' and any(
                arg in ('-name', '-iname') and args[i + 1] in names
                for i, arg in enumerate(args[:-1])):
            return True
    return False


class AdapterRuntime:
    def __init__(self, client: JvApiClient, max_requests: int = 40, heartbeat: float = 5.0):
        if not 1 <= max_requests <= 500 or not 0 < heartbeat <= 30:
            raise JvError('Invalid adapter limits')
        self.client = client
        self.max_requests = max_requests
        self.heartbeat = heartbeat
        self.key = secrets.token_urlsafe(32)
        self.server = None
        self.thread = None
        self.lock = threading.Lock()
        self.requests = 0
        self.cancel = threading.Event()
        self.status = 'idle'
        self.last_job_id: str | None = None
        self.last_error: str | None = None
        self.signatures: dict[str, int] = {}
        self.rust_discovery_probes = 0
        self.worker: threading.Thread | None = None
        self.notices = queue.SimpleQueue()
        self.response_repairs = 0

    def begin_turn(self):
        if self.lock.locked():
            raise JvError('A previous model request is still stopping; exit and restart rather than duplicating it')
        self.requests = 0
        self.signatures = {}
        self.rust_discovery_probes = 0
        self.last_error = None
        self.last_job_id = None
        self.response_repairs = 0
        while not self.notices.empty():
            self.notices.get_nowait()
        self.cancel = threading.Event()
        self.status = 'waiting for agent'

    def start(self) -> int:
        if self.server:
            raise JvError('Adapter is already running')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ResponsesAdapterHandler)
        self.server.daemon_threads = True
        self.server.runtime = self
        self.thread = threading.Thread(target=self.server.serve_forever, name='jv-adapter', daemon=True)
        self.thread.start()
        return self.server.server_address[1]

    def close(self):
        self.cancel.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        if self.worker:
            self.worker.join(timeout=1)
        self.server = None
        self.thread = None

    def _completed_job(self, prompt: str, repairing: bool = False) -> dict:
        # Submission and polling errors deliberately escape. A new correction
        # job is allowed only after a confirmed succeeded job with rejected text.
        if self.cancel.is_set():
            raise Cancelled('Turn cancelled before submission')
        if self.requests >= self.max_requests:
            raise JvError('Model-request limit reached for this turn; split the task into smaller steps')
        self.requests += 1
        if repairing:
            self.response_repairs += 1
        self.status = 'submitting model job'
        created = self.client.submit_job(prompt)
        self.last_job_id = created['id']

        def progress(job):
            self.status = 'JV job ' + job['id'] + ': ' + job['status']

        terminal = self.client.wait_for_job(created['id'], cancel=self.cancel, progress=progress,
                                             conversation_id=created['conversation_id'])
        if self.cancel.is_set():
            raise Cancelled('Turn cancelled; remote work may have completed')
        if terminal['status'] != 'succeeded':
            raise JvError(f'JV job {created["id"]} failed; use jvcli job {created["id"]} to inspect its status')
        return terminal

    def infer(self, request: dict, prompt: str, catalog: dict) -> list[dict]:
        next_prompt = prompt
        for attempt in range(MAX_RESPONSE_REPAIRS + 1):
            terminal = self._completed_job(next_prompt, repairing=attempt > 0)
            try:
                answer = terminal.get('answer')
                if not isinstance(answer, str):
                    raise ProtocolError('JV job completed without a text answer')
                items = parse_agent_output(answer, catalog)
                if any(item['type'] == 'message' and provider_failure(item['content'][0]['text'])
                       for item in items):
                    raise ProtocolError('JV provider returned a generic error answer')
                if request.get('tool_choice') == 'required' and any(item['type'] == 'message' for item in items):
                    raise ProtocolError('Model returned text when a tool call was required')
            except ProtocolError as exc:
                if self.cancel.is_set():
                    raise Cancelled('Turn cancelled before response correction') from None
                if attempt == MAX_RESPONSE_REPAIRS or self.requests >= self.max_requests:
                    raise ProtocolError(
                        f'{exc}. Response correction stopped after {attempt} extra model jobs; '
                        f'no tools from the rejected responses were executed. '
                        f'Inspect: jvcli job {self.last_job_id} --json') from None
                next_prompt = response_repair_prompt(prompt, str(exc))
                self.notices.put(
                    f'JV job {self.last_job_id}: {exc}. '
                    f'Requesting corrected response ({attempt + 1}/{MAX_RESPONSE_REPAIRS}); '
                    'no tools from the rejected response ran.')
                continue
            break
        response_files = (terminal.get('response') or {}).get('files', []) if isinstance(terminal.get('response') or {}, dict) else []
        if response_files:
            note = f'\n\n[Generated files are available. Run: jvcli job {self.last_job_id} --download-dir ./jv-output]'
            for item in items:
                if item['type'] == 'message':
                    item['content'][0]['text'] += note
                    break
        # Validate the whole batch before committing counters or emitting tools.
        # Changing whitespace, search roots or PATH must not permit the observed
        # Rust discovery loop to consume the entire turn's model budget.
        signatures = self.signatures.copy()
        probes = self.rust_discovery_probes
        for item in items:
            if item['type'] not in ('function_call', 'custom_tool_call'):
                continue
            action = {k: item.get(k) for k in ('type', 'name', 'namespace', 'arguments', 'input')}
            if item['type'] == 'function_call':
                action['arguments'] = strict_json(item['arguments'])
                if item['name'] == 'shell_command':
                    probes += int(rust_discovery_probe(action['arguments'].get('command', '')))
            signature = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
            signatures[signature] = signatures.get(signature, 0) + 1
            if signatures[signature] > 3:
                raise ProtocolError('Model repeated the same tool action four times; stopped to prevent a loop')
            if probes > MAX_RUST_DISCOVERY_PROBES:
                raise ProtocolError(
                    'Rust prerequisite discovery limit reached (6 probes per turn). '
                    'Stopped repeated compiler searches; no tools from this response were executed. '
                    'Rust availability is unresolved: no installation was performed by this guard. '
                    'Use /new for source-only work or explicitly provide an authorized toolchain; '
                    'do not borrow another project\'s private tools.')
        self.signatures = signatures
        self.rust_discovery_probes = probes
        self.status = 'model response received'
        return items


class ResponsesAdapterHandler(BaseHTTPRequestHandler):
    server_version = 'JVAdapter/0.3'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    @property
    def runtime(self) -> AdapterRuntime:
        return self.server.runtime

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        pass  # No access/credential logs.

    def _json_response(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def _authorized(self):
        expected = f'127.0.0.1:{self.server.server_address[1]}'
        if self.headers.get('Host') != expected or self.headers.get('Origin') is not None:
            self._json_response(403, {'error': {'message': 'Untrusted local request origin'}})
            return False
        headers = self.headers.get_all('Authorization', [])
        if len(headers) != 1 or not secrets.compare_digest(headers[0], 'Bearer ' + self.runtime.key):
            self._json_response(401, {'error': {'message': 'Local adapter authentication required'}})
            return False
        return True

    def do_GET(self):
        try:
            if not self._authorized():
                return
            if self.path == '/healthz':
                self._json_response(200, {'ok': True})
            elif self.path == '/v1/models':
                self._json_response(200, {'object': 'list', 'data': [{'id': 'jv-local', 'object': 'model', 'owned_by': 'jv'}]})
            else:
                self._json_response(404, {'error': {'message': 'Not found'}})
        except (OSError, ValueError):
            self.close_connection = True

    def do_POST(self):
        streaming = False
        locked = False
        response_id = 'resp_jv_' + uuid.uuid4().hex
        try:
            if not self._authorized():
                return
            if self.path != '/v1/responses':
                self._json_response(404, {'error': {'message': 'Only /v1/responses is supported'}})
                return
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding', 'identity') != 'identity':
                self._json_response(415, {'error': {'message': 'Send uncompressed JSON with Content-Length'}})
                return
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_JSON_BYTES:
                self._json_response(400, {'error': {'message': 'Invalid request size'}})
                return
            if self.headers.get_content_type() != 'application/json':
                self._json_response(415, {'error': {'message': 'Content-Type must be application/json'}})
                return
            body = self.rfile.read(int(lengths[0]))
            if len(body) != int(lengths[0]):
                raise ProtocolError('Incomplete request body')
            try:
                request = strict_json(body)
            except (ValueError, UnicodeError, RecursionError):
                raise ProtocolError('Malformed request JSON') from None
            if not isinstance(request, dict) or request.get('model', 'jv-local') != 'jv-local':
                raise ProtocolError('Invalid request or unknown model')
            if type(request.get('stream', True)) is not bool:
                raise ProtocolError('stream must be a boolean')
            prompt, catalog = build_jv_prompt(request)
            locked = self.runtime.lock.acquire(blocking=False)
            if not locked:
                self._json_response(409, {'error': {'message': 'A model request is already in progress'}})
                return
            if request.get('stream', True):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self.end_headers()
                streaming = True
                self.close_connection = True
                self._sequence = 0
                self._event({'type': 'response.created', 'response': {'id': response_id, 'object': 'response', 'status': 'in_progress', 'output': []}})
                completed = threading.Event()
                result = {}

                def work():
                    try:
                        result['items'] = self.runtime.infer(request, prompt, catalog)
                    except JvError as exc:
                        result['error'] = exc
                    except Exception:
                        result['error'] = JvError('Adapter could not process the model response')
                    finally:
                        completed.set()

                worker = threading.Thread(target=work, name='jv-job', daemon=True)
                self.runtime.worker = worker
                worker.start()
                while not completed.wait(self.runtime.heartbeat):
                    if self.runtime.cancel.is_set():
                        raise Cancelled('Local turn cancelled; submitted remote jobs may continue')
                    self.wfile.write(b': jv-keepalive\n\n')
                    self.wfile.flush()
                if 'error' in result:
                    raise result['error']
                items = result['items']
                self._finish_sse(response_id, items)
            else:
                items = self.runtime.infer(request, prompt, catalog)
                self._json_response(200, {'id': response_id, 'object': 'response', 'status': 'completed', 'output': items})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.runtime.cancel.set()
            self.close_connection = True
        except JvError as exc:
            self.runtime.last_error = str(exc)
            if streaming:
                try:
                    self._event({'type': 'error', 'code': 'jv_adapter_error', 'message': str(exc)})
                    self._event({'type': 'response.failed', 'response': {'id': response_id, 'status': 'failed', 'error': {'code': 'jv_adapter_error', 'message': str(exc)}}})
                except OSError:
                    pass
            else:
                self._json_response(400 if isinstance(exc, ProtocolError) else 502, {'error': {'message': str(exc), 'type': 'jv_adapter_error'}})
        except Exception:
            self.runtime.last_error = 'Adapter request failed'
            if not streaming:
                try:
                    self._json_response(500, {'error': {'message': 'Adapter request failed'}})
                except OSError:
                    pass
        finally:
            if locked:
                # On disconnect do not accept new jobs until the worker stopped.
                worker = self.runtime.worker
                if worker and worker.is_alive():
                    self.runtime.cancel.set()
                    worker.join(timeout=self.runtime.client.config.request_timeout + 1)
                if worker and worker.is_alive():
                    # Keep the gate closed even if an in-flight HTTP read takes
                    # longer than its socket timeout. A second job must not race it.
                    def release_when_stopped():
                        worker.join()
                        self.runtime.lock.release()
                    threading.Thread(target=release_when_stopped, name='jv-request-cleanup', daemon=True).start()
                else:
                    self.runtime.lock.release()

    def _event(self, event):
        event['sequence_number'] = self._sequence
        self._sequence += 1
        self.wfile.write(b'data: ' + json.dumps(event, ensure_ascii=False, separators=(',', ':')).encode() + b'\n\n')
        self.wfile.flush()

    def _finish_sse(self, response_id, items):
        for index, item in enumerate(items):
            initial = dict(item)
            initial['status'] = 'in_progress'
            if item['type'] == 'function_call':
                initial['arguments'] = ''
            elif item['type'] == 'custom_tool_call':
                initial['input'] = ''
            elif item['type'] == 'message':
                initial['content'] = []
            self._event({'type': 'response.output_item.added', 'output_index': index, 'item': initial})
            if item['type'] == 'message':
                text = item['content'][0]['text']
                self._event({'type': 'response.content_part.added', 'item_id': item['id'], 'output_index': index, 'content_index': 0,
                             'part': {'type': 'output_text', 'text': '', 'annotations': []}})
                self._event({'type': 'response.output_text.delta', 'item_id': item['id'], 'output_index': index, 'content_index': 0, 'delta': text})
                self._event({'type': 'response.output_text.done', 'item_id': item['id'], 'output_index': index, 'content_index': 0, 'text': text})
                self._event({'type': 'response.content_part.done', 'item_id': item['id'], 'output_index': index, 'content_index': 0, 'part': item['content'][0]})
            elif item['type'] == 'function_call':
                self._event({'type': 'response.function_call_arguments.delta', 'item_id': item['id'], 'output_index': index, 'delta': item['arguments']})
                self._event({'type': 'response.function_call_arguments.done', 'item_id': item['id'], 'output_index': index, 'arguments': item['arguments']})
            # Custom call input is delivered atomically in output_item.done.
            self._event({'type': 'response.output_item.done', 'output_index': index, 'item': item})
        self._event({'type': 'response.completed', 'response': {'id': response_id, 'object': 'response', 'status': 'completed', 'output': items}})
        # JV exposes no authoritative token usage. Do not invent billing counts.
        self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()
