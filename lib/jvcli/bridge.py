"""Protocol 1 machine frontend. Production dependencies are injected only in tests.

The main thread owns auth/session/lifecycle. One turn worker owns run_turn until
joined; a size-one result queue transfers its result. Emitter owns stdout.
No request changes cwd, the engine, environment, or the server protocol.
"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import sys
import threading
import uuid

from . import cli
from .bridge_io import EOF, OVERSIZE, Emitter, LineReader
from .safety import JvError, redact_data, strict_json, terminal_text
from .transport import validate_base_url

PROTOCOL = 1
ID = re.compile(r'[A-Za-z0-9_-]{1,100}\Z')
ERRORS = {
    'invalid_request': 'Request is not valid',
    'unsupported_protocol': 'Protocol version is not supported',
    'not_authenticated': 'Authentication is required',
    'authentication_failed': 'Authentication failed',
    'session_not_started': 'Start a session first',
    'session_busy': 'Close this bridge before replacing its session or account',
    'turn_busy': 'A turn is still running or cleaning up',
    'invalid_session': 'Session could not be opened with this workspace and account',
    'workspace_error': 'Choose a safe project workspace before starting the bridge',
    'engine_error': 'The local engine did not complete the turn',
    'cancel_error': 'No matching active turn',
    'internal_error': 'The local bridge could not complete the operation',
    'input_limit': 'Request line exceeds the size limit',
}
SCHEMAS = {
    'auth.login': ({'username', 'base_url', 'password'}, set()),
    'session.start': (set(), {'resume_session_id', 'read_only', 'allow_network'}),
    'turn.start': ({'text'}, set()),
    'turn.cancel': ({'turn_id'}, set()),
    'thread.new': (set(), set()),
    'bridge.shutdown': (set(), set()),
}


class RequestError(Exception):
    def __init__(self, code):
        self.code = code


def identifier(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def string(value, maximum, *, controls=False):
    return (isinstance(value, str) and bool(value.strip())
            and len(value.encode('utf-8')) <= maximum
            and (controls or not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)))


def validate(request):
    if not isinstance(request, dict) or not identifier(request.get('request_id')):
        raise RequestError('invalid_request')
    if type(request.get('protocol', 1)) is not int or request.get('protocol', 1) != PROTOCOL:
        raise RequestError('unsupported_protocol')
    typ = request.get('type')
    if not isinstance(typ, str) or typ not in SCHEMAS:
        raise RequestError('invalid_request')
    required, optional = SCHEMAS[typ]
    if not required <= request.keys() or request.keys() - required - optional - {'type', 'protocol', 'request_id'}:
        raise RequestError('invalid_request')
    if typ == 'auth.login':
        if not (string(request['username'], 256) and string(request['base_url'], 2048)
                and string(request['password'], 16384, controls=True)):
            raise RequestError('invalid_request')
    if typ == 'session.start':
        if any(type(request[k]) is not bool for k in ('read_only', 'allow_network') if k in request):
            raise RequestError('invalid_request')
        if 'resume_session_id' in request and not identifier(request['resume_session_id']):
            raise RequestError('invalid_request')
        if request.get('read_only', False) and request.get('allow_network', False):
            raise RequestError('invalid_request')
    if typ == 'turn.start' and not string(request['text'], 100 * 1024, controls=True):
        raise RequestError('invalid_request')
    if typ == 'turn.cancel' and not identifier(request['turn_id']):
        raise RequestError('invalid_request')
    return typ


def bounded(value, limit=8192):
    if not isinstance(value, str):
        return ''
    return terminal_text(value).encode('utf-8')[:limit].decode('utf-8', 'ignore')


def normalize(event):
    """Allowlisted engine fields only. Turn finality comes from run_turn's result."""
    typ = event.get('type')
    if typ in ('thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'error'):
        return None
    item = event.get('item')
    if typ not in ('item.started', 'item.completed') or not isinstance(item, dict):
        return None
    kind = item.get('type')
    if kind == 'agent_message' and typ == 'item.completed':
        return {'type': 'assistant.message', 'text': bounded(item.get('text'), 32768)}
    if kind == 'command_execution':
        result = {'type': 'command.started' if typ == 'item.started' else 'command.completed',
                  'command': bounded(item.get('command'))}
        if typ == 'item.completed':
            code = item.get('exit_code')
            result.update(exit_code=code if type(code) is int and abs(code) <= 2**31 else None,
                          output=bounded(item.get('aggregated_output'), 16384))
        return result
    if kind in ('file_change', 'file_changes') and typ == 'item.completed':
        changes = item.get('changes', [])
        if not isinstance(changes, list):
            changes = []
        return {'type': 'files.changed', 'changes': [
            {'path': bounded(c.get('path'), 1024),
             'kind': c.get('kind') if c.get('kind') in ('add', 'delete', 'update') else 'unknown'}
            for c in changes[:50] if isinstance(c, dict) and isinstance(c.get('path'), str)]}
    if kind in ('mcp_tool_call', 'web_search') and typ == 'item.started':
        return {'type': 'tool.started', 'name': bounded(item.get('tool', kind), 256)}
    return None


class Bridge:
    def __init__(self, emitter, workspace, client_factory=None, session_factory=None):
        self.out, self.workspace = emitter, workspace
        self.client_factory = client_factory or cli._new_client
        self.session_factory = session_factory or cli._session_runtime
        self.client = self.account = self.context = self.session = None
        self.worker = self.turn_id = self.turn_request = None
        self.cancel = threading.Event()
        self.results = queue.Queue(maxsize=1)
        self.stopping = False
        self.fatal = False
        self.closed = False

    def emit(self, typ, **fields):
        frame = {'type': typ, **fields}
        secrets = (getattr(self.client, '_token', '') or '',)
        if self.session:
            secrets += (self.session.runtime.key,)
        self.out.emit(redact_data(frame, secrets))

    def error(self, code, request_id=None):
        self.emit('request.error', request_id=request_id, code=code, message=ERRORS[code])

    def logout(self):
        client, self.client = self.client, None
        self.account = None
        if client:
            try:
                client.logout()
            except Exception:
                # Local token ownership ends even if server revocation is unavailable.
                client._token = None

    def request(self, request):
        rid = request.get('request_id') if isinstance(request, dict) else None
        rid = rid if identifier(rid) else None
        try:
            typ = validate(request)
            if typ == 'bridge.shutdown':
                self.stopping = True
                self.cancel.set()
                self.emit('bridge.stopping', request_id=rid)
                return
            if typ == 'auth.login':
                if self.session:
                    raise RequestError('session_busy')
                try:
                    base = validate_base_url(request['base_url'])
                except JvError:
                    raise RequestError('invalid_request') from None
                self.logout()
                password = request.pop('password')
                try:
                    cli._ensure_state()
                    self.client = self.client_factory(base)
                    self.client.login(request['username'].strip(), password)
                except Exception:
                    self.logout()
                    raise RequestError('authentication_failed') from None
                finally:
                    del password
                self.account = (self.client, request['username'].strip(), base)
                self.emit('auth.succeeded', request_id=rid)
                return
            if not self.client:
                raise RequestError('not_authenticated')
            if typ == 'session.start':
                if self.session:
                    raise RequestError('session_busy')
                # The protocol cannot switch cwd, including through an injected factory.
                if cli._workspace_check(Path.cwd()) != self.workspace:
                    raise RequestError('workspace_error')
                try:
                    self.context = self.session_factory(
                        resume=request.get('resume_session_id'),
                        read_only=request.get('read_only', False),
                        allow_network=request.get('allow_network'), account=self.account)
                    self.session = self.context.__enter__()
                except Exception:
                    self.context = None
                    raise RequestError('invalid_session') from None
                self.emit('session.started', request_id=rid, session_id=self.session.sid,
                          workspace=str(self.workspace),
                          sandbox='read-only' if self.session.read_only else 'workspace-write',
                          network=self.session.allow_network,
                          transport=self.session.metadata['transport_mode'],
                          thread_id=self.session.thread_id)
                return
            if not self.session:
                raise RequestError('session_not_started')
            if typ == 'turn.cancel':
                if not self.worker or request['turn_id'] != self.turn_id:
                    raise RequestError('cancel_error')
                self.cancel.set()
                self.session.runtime.cancel.set()
                self.emit('turn.cancel.accepted', request_id=rid, turn_id=self.turn_id,
                          local=True, remote_state='unknown')
                return
            if self.worker or self.session.runtime.lock.locked():
                raise RequestError('turn_busy')
            if typ == 'thread.new':
                self.session.new_thread()
                self.emit('thread.started', request_id=rid, thread_id=None)
                return
            self.turn_id = uuid.uuid4().hex
            self.turn_request = rid
            self.cancel = threading.Event()
            self.emit('turn.started', request_id=rid, turn_id=self.turn_id)
            text = request.pop('text')
            self.worker = threading.Thread(target=self._turn, args=(text,),
                                           name='bridge-turn', daemon=True)
            self.worker.start()
        except RequestError as exc:
            self.error(exc.code, rid)
        except (UnicodeError, ValueError, TypeError):
            self.error('invalid_request', rid)
        except BrokenPipeError:
            raise
        except Exception:
            self.error('internal_error', rid)

    def _turn(self, text):
        def sink(event):
            frame = normalize(event)
            if frame:
                self.emit(frame.pop('type'), turn_id=self.turn_id, **frame)
        try:
            rc = self.session.run_turn(text, event_sink=sink, render_terminal=False,
                                       cancel_event=self.cancel)
        except Exception:
            rc = 1
        finally:
            del text
        self.results.put(rc)

    def reap(self):
        try:
            rc = self.results.get_nowait()
        except queue.Empty:
            return
        self.worker.join()
        cancelled = self.cancel.is_set() or rc == 130
        typ = 'turn.cancelled' if cancelled else ('turn.completed' if rc == 0 else 'turn.failed')
        fields = {'request_id': self.turn_request, 'turn_id': self.turn_id}
        if cancelled:
            fields.update(local=True, remote_state='unknown')
        elif rc:
            fields.update(code='engine_error', message=ERRORS['engine_error'])
        self.worker = None
        self.emit(typ, **fields)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel.set()
        if self.session:
            self.session.runtime.cancel.set()
        if self.worker:
            # _run_engine's cancellation/wait/readers have bounded cleanup.
            self.worker.join(15)
            if self.worker.is_alive():
                self.fatal = True
                # Never tear down a session concurrently with its turn owner.
                return
            try:
                self.reap()
            except BrokenPipeError:
                pass
        try:
            if self.context:
                self.context.__exit__(None, None, None)
        except Exception:
            self.fatal = True
        finally:
            self.session = self.context = None
            self.logout()


def serve(*, input_fd=None, output_fd=None, client_factory=None, session_factory=None):
    """Internal injection only: production parser exposes no test/bypass flags."""
    output = bridge = None
    fatal = False
    try:
        output = Emitter(sys.stdout.fileno() if output_fd is None else output_fd)
        try:
            workspace = cli._workspace_check(Path.cwd())
        except Exception:
            output.emit({'type': 'request.error', 'request_id': None,
                         'code': 'workspace_error', 'message': ERRORS['workspace_error']})
            return 2
        bridge = Bridge(output, workspace, client_factory, session_factory)
        bridge.emit('bridge.ready', protocol=PROTOCOL, cli_version=cli.VERSION,
                    workspace=str(workspace), capabilities={'auth': 'stdio-memory',
                    'session': True, 'resume': True, 'cancel': 'local', 'images': False,
                    'thread_new': True})
        reader = LineReader(sys.stdin.fileno() if input_fd is None else input_fd)
        while not bridge.stopping and not output.failed.is_set():
            bridge.reap()
            line = reader.next()
            if line is EOF:
                break
            if line is OVERSIZE:
                bridge.error('input_limit')
                continue
            if line is None or not line.strip():
                continue
            try:
                request = strict_json(line.decode('utf-8'))
            except (ValueError, UnicodeError, RecursionError):
                bridge.error('invalid_request')
                continue
            finally:
                line = None
            try:
                bridge.request(request)
            finally:
                request = None
    except (Exception, KeyboardInterrupt):
        fatal = True
    finally:
        if bridge:
            bridge.close()
        if output:
            output.close()
    return 2 if fatal or (output and output.failed.is_set()) or (bridge and bridge.fatal) else 0
