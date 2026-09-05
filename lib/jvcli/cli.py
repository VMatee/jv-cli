"""JV CLI launcher, local configuration and session management."""
from __future__ import annotations

import argparse
from collections import deque
import contextlib
import datetime
import fcntl
import getpass
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
import warnings

from .adapter import AdapterRuntime
from .protocol import BASE_AGENT_INSTRUCTIONS
from .safety import (JvError, atomic_write, no_symlink_path, positive_number,
                     private_dir, read_private_json, redact, redact_data, strict_json, terminal_text)
from .transport import DEFAULT_BASE_URL, JvApiClient, JvClientConfig, validate_base_url

ENGINE_VERSION = '0.149.1'
APP_ROOT = Path(__file__).resolve().parents[2]
VERSION = (APP_ROOT / 'VERSION').read_text(encoding='utf-8').strip()
STATE_DIR = Path(os.environ.get('JVCLI_HOME', str(APP_ROOT / '.state'))).expanduser().absolute()
CONFIG_PATH = STATE_DIR / 'config.json'
LOCAL_RUNTIME = APP_ROOT / 'runtime'


def say(message, *, error=False):
    print(terminal_text(message), file=sys.stderr, flush=True)


def _ensure_state():
    private_dir(STATE_DIR)


def _load_disk_config():
    config = read_private_json(CONFIG_PATH)
    allowed = {'base_url', 'username'}
    if set(config) - allowed:
        raise JvError('config.json contains unknown fields; only base_url and username are allowed. Never store passwords there')
    if 'base_url' in config:
        validate_base_url(config['base_url'])
    if 'username' in config:
        value = config['username']
        if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
            raise JvError('Invalid configured username')
    return config


def _save_disk_config(config):
    _ensure_state()
    atomic_write(CONFIG_PATH, json.dumps({k: v for k, v in config.items() if k in ('username', 'base_url')}, indent=2) + '\n')


def _resolve_account(username=None, base_url=None, prompt=True):
    config = _load_disk_config()
    base = validate_base_url(base_url or os.environ.get('JV_API_BASE_URL') or config.get('base_url') or DEFAULT_BASE_URL)
    user = username or os.environ.get('JV_API_USERNAME') or config.get('username')
    if not user and prompt and sys.stdin.isatty():
        print('JV LLM username: ', end='', file=sys.stderr, flush=True)
        user = input().strip()
    if not isinstance(user, str) or not user.strip():
        raise JvError('Configure a username with jvcli login, or set JV_API_USERNAME')
    return base, user.strip()


def _password():
    # Remove automation secrets from this process environment before child launch.
    value = os.environ.pop('JV_API_PASSWORD', None)
    if value is None:
        if not sys.stdin.isatty():
            raise JvError('For noninteractive use, supply JV_API_PASSWORD through a trusted secret source')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            try:
                value = getpass.getpass('JV LLM password: ')
            except getpass.GetPassWarning:
                raise JvError('Cannot hide the password on this terminal; refusing an echoed password prompt') from None
    if not value:
        raise JvError('Password is empty')
    return value


def _new_client(base):
    return JvApiClient(JvClientConfig(base_url=base,
        poll_interval=positive_number(os.environ.get('JVCLI_POLL_INTERVAL', '2'), 'JVCLI_POLL_INTERVAL'),
        wait_timeout=positive_number(os.environ.get('JVCLI_WAIT_TIMEOUT', '3600'), 'JVCLI_WAIT_TIMEOUT'),
        request_timeout=positive_number(os.environ.get('JVCLI_REQUEST_TIMEOUT', '30'), 'JVCLI_REQUEST_TIMEOUT'),
        temp_dir=private_dir(STATE_DIR / 'tmp')))


def _login_client(username=None, base_url=None):
    base, user = _resolve_account(username, base_url)
    client = _new_client(base)
    password = _password()
    try:
        client.login(user, password)
    finally:
        del password
    try:
        _save_disk_config({'base_url': base, 'username': user})
    except Exception:
        _logout(client)
        raise
    say(f'Signed in as {user}; JV API: {base}')
    return client, user


def _logout(client):
    try:
        client.logout()
    except JvError:
        say('Warning: token cleared locally, but server revocation could not be confirmed')


def _find_engine():
    explicit = os.environ.get('JVCLI_CODEX_BIN')
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise JvError('JVCLI_CODEX_BIN does not point to an executable file')
        return str(path)
    for path in (LOCAL_RUNTIME / 'node_modules/.bin/codex', LOCAL_RUNTIME / 'bin/codex'):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _version_of_engine(engine):
    try:
        result = subprocess.run([engine, '--version'], capture_output=True, text=True, timeout=10,
                                env=_diagnostic_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise JvError('Agent engine could not start; run ./install.sh') from None
    match = re.search(r'\b\d+\.\d+\.\d+(?:[-+][\w.-]+)?', result.stdout)
    if result.returncode or not match:
        raise JvError('Agent engine version check failed')
    return match.group(0)


def _minimal_env():
    keep = ('PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'USER', 'LOGNAME', 'SHELL', 'TZ')
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1', 'NO_COLOR': '1'})
    return env


def _diagnostic_env():
    env = _minimal_env()
    home = private_dir(STATE_DIR / 'diagnostics' / 'home')
    engine = private_dir(STATE_DIR / 'diagnostics' / 'engine')
    tmp = private_dir(STATE_DIR / 'diagnostics' / 'tmp')
    env.update(HOME=str(home), CODEX_HOME=str(engine), TMPDIR=str(tmp))
    return env


def _toml(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return '[' + ', '.join(_toml(x) for x in value) + ']'
    if isinstance(value, dict):
        return '{ ' + ', '.join(_toml(k) + ' = ' + _toml(v) for k, v in value.items()) + ' }'
    raise JvError('Unsupported configuration value')


def _model_catalog():
    # Pinned-engine schema. This is adapter capacity metadata, not a claim about
    # the actual server-assigned model's context capacity.
    return {'models': [{'slug': 'jv-local', 'display_name': 'JV Local', 'description': 'JV job API adapter',
        'default_reasoning_level': None, 'supported_reasoning_levels': [], 'shell_type': 'shell_command',
        'visibility': 'list', 'supported_in_api': True, 'priority': 0, 'availability_nux': None,
        'upgrade': None, 'support_verbosity': False, 'default_verbosity': None,
        'apply_patch_tool_type': 'freeform', 'truncation_policy': {'mode': 'tokens', 'limit': 10000},
        'context_window': 32768, 'experimental_supported_tools': [], 'tool_mode': 'direct',
        'base_instructions': BASE_AGENT_INSTRUCTIONS}]}


def _write_engine_config(session_dir, port, read_only=False, allow_network=False):
    engine_home = private_dir(session_dir / 'engine')
    tool_home = private_dir(session_dir / 'tool-home')
    tmp = private_dir(session_dir / 'tmp')
    catalog = session_dir / 'model_catalog.json'
    instructions = session_dir / 'instructions.md'
    atomic_write(catalog, json.dumps(_model_catalog(), indent=2) + '\n')
    atomic_write(instructions, BASE_AGENT_INSTRUCTIONS)
    config = {
        'model': 'jv-local', 'model_provider': 'jv', 'model_catalog_json': str(catalog),
        'model_instructions_file': str(instructions), 'approval_policy': 'never',
        'sandbox_mode': 'read-only' if read_only else 'workspace-write', 'hide_agent_reasoning': True,
        'web_search': 'disabled', 'check_for_update_on_startup': False,
        'features': {'code_mode': False, 'code_mode_only': False, 'shell_tool': True,
                     'unified_exec': False, 'apply_patch_freeform': True},
        'analytics': {'enabled': False},
        'model_providers': {'jv': {'name': 'JV LLM', 'base_url': f'http://127.0.0.1:{port}/v1',
            'wire_api': 'responses', 'requires_openai_auth': False, 'supports_websockets': False,
            'env_key': 'JVCLI_ADAPTER_KEY', 'request_max_retries': 0, 'stream_max_retries': 0,
            'stream_idle_timeout_ms': 120000}},
        'sandbox_workspace_write': {'network_access': bool(allow_network), 'exclude_slash_tmp': True,
            'exclude_tmpdir_env_var': False, 'writable_roots': [str(tool_home)]},
        'shell_environment_policy': {'inherit': 'core', 'ignore_default_excludes': False,
            'exclude': ['JVCLI_ADAPTER_KEY', 'JV_API_PASSWORD', 'JV_API_USERNAME'],
            'set': {'HOME': str(tool_home), 'TMPDIR': str(tmp), 'XDG_CACHE_HOME': str(tool_home / '.cache'),
                    'PIP_REQUIRE_VIRTUALENV': 'true', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}},
    }
    atomic_write(engine_home / 'config.toml', '# Managed by JV CLI; no password or token stored here.\n' +
                 '\n'.join(f'{key} = {_toml(value)}' for key, value in config.items()) + '\n')
    # CLI overrides outrank project config for safety/provider routing. Tables are
    # serialized as TOML inline tables, not invalid JSON object syntax.
    overrides = []
    for key, value in config.items():
        overrides.extend(['-c', f'{key}={_toml(value)}'])
    return overrides


def _engine_env(session_dir=None, adapter_key=None):
    env = _minimal_env()
    if session_dir:
        env.update({'CODEX_HOME': str(session_dir / 'engine'), 'HOME': str(session_dir / 'tool-home'),
                    'TMPDIR': str(session_dir / 'tmp'), 'XDG_CACHE_HOME': str(session_dir / 'tool-home/.cache')})
    if adapter_key:
        env['JVCLI_ADAPTER_KEY'] = adapter_key
    return env


def _describe_item(item, started=False):
    kind = item.get('type')
    if kind == 'agent_message' and not started:
        text = item.get('text')
        if isinstance(text, str) and text.strip():
            print(terminal_text(text).rstrip(), flush=True)
    elif kind == 'command_execution':
        if started:
            say('running: ' + str(item.get('command', item.get('cmd', 'command')))[:1000])
        else:
            code = item.get('exit_code')
            say(f'command completed (exit {code})' if code is not None else 'command completed')
            if code not in (0, '0', None):
                output = item.get('aggregated_output') or item.get('output')
                if isinstance(output, str):
                    say(output[-4000:])
    elif kind in ('file_change', 'file_changes') and not started:
        changes = item.get('changes', [])
        names = [str(c.get('path', 'file')) for c in changes[:12] if isinstance(c, dict)]
        say('files updated: ' + ', '.join(names))
    elif kind in ('mcp_tool_call', 'tool_call') and started:
        say('using tool: ' + str(item.get('name') or item.get('tool') or 'tool'))


def _stop_process(process):
    # This is called on cancellation/failure, not normal completion. The
    # parent can exit before its children, so always address the process group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait(timeout=3)


def _run_engine(engine, prompt, thread_id, *, session_dir=None, overrides=(), runtime=None,
                json_mode=False, turn_timeout=3600):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 100 * 1024:
        raise JvError('Prompt must be nonempty and no larger than 100 KiB')
    # Prompt travels over stdin, not process arguments or shell expansion.
    command = [engine, *overrides, 'exec']
    if thread_id:
        command += ['resume', thread_id]
    command += ['--json', '--skip-git-repo-check', '--ignore-rules']
    if not thread_id:
        command += ['--color', 'never']
    command += ['-']
    process = subprocess.Popen(command, env=_engine_env(session_dir, runtime.key if runtime else None),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        text=True, encoding='utf-8', errors='replace', bufsize=1)
    events = queue.Queue(maxsize=32)
    stderr_lines = deque(maxlen=100)
    secrets = (runtime.key, runtime.client._token or '') if runtime else ()

    stopping = threading.Event()

    def enqueue(kind, value):
        while not stopping.is_set():
            try:
                events.put((kind, value), timeout=0.1)
                return True
            except queue.Full:
                pass
        return False

    def read_stdout():
        try:
            for line in iter(lambda: process.stdout.readline(1024 * 1024 + 1), ''):
                if not enqueue('line', line):
                    return
        except (OSError, ValueError):
            pass
        finally:
            enqueue('eof', '')

    def read_stderr():
        try:
            for line in iter(lambda: process.stderr.readline(8192), ''):
                stderr_lines.append(redact(line, secrets))
        except (OSError, ValueError):
            pass

    def write_prompt():
        # A hung child may not read stdin. Do not let a full pipe disable the
        # main thread's turn deadline or cancellation handling.
        try:
            process.stdin.write(prompt + '\n')
            process.stdin.close()
        except (OSError, ValueError):
            enqueue('input_error', 'Agent could not receive the prompt')

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True),
               threading.Thread(target=write_prompt, daemon=True)]
    for reader in readers:
        reader.start()
    current = thread_id
    saw_message = False
    completed = False
    failed = False
    forced_rc = None
    started = time.monotonic()
    last_progress = started
    try:
        while True:
            if runtime:
                while True:
                    try:
                        say(redact(runtime.notices.get_nowait(), secrets))
                    except queue.Empty:
                        break
            if time.monotonic() - started >= turn_timeout:
                if runtime:
                    runtime.cancel.set()
                say('Turn timed out. Local agent stopped; an already submitted remote job may continue.')
                forced_rc = 124
                break
            try:
                kind, raw = events.get(timeout=0.2)
            except queue.Empty:
                if time.monotonic() - last_progress >= 15:
                    say('Waiting: ' + (runtime.status if runtime else 'agent engine'))
                    last_progress = time.monotonic()
                continue
            if kind == 'eof':
                break
            if kind == 'input_error':
                failed = True
                say(raw)
                break
            last_progress = time.monotonic()
            if len(raw.encode()) > 1024 * 1024:
                failed = True
                say('Agent event exceeded the allowed size')
                break
            try:
                event = strict_json(raw)
                if not isinstance(event, dict):
                    raise ValueError()
            except (ValueError, UnicodeError, RecursionError):
                failed = True
                say('Agent returned malformed JSON output')
                break
            if json_mode:
                # Redaction is applied before parsing again to avoid escape issues.
                print(json.dumps(redact_data(event, secrets), ensure_ascii=False), flush=True)
            typ = event.get('type')
            if typ == 'thread.started' and isinstance(event.get('thread_id'), str):
                current = event['thread_id']
            elif typ in ('item.started', 'item.completed'):
                item = event.get('item')
                if isinstance(item, dict):
                    if typ == 'item.completed' and item.get('type') == 'agent_message' and isinstance(item.get('text'), str) and item['text'].strip():
                        saw_message = True
                    if not json_mode:
                        # Redact any accidental echo of known secrets before display.
                        item = redact_data(item, secrets)
                        _describe_item(item, started=typ == 'item.started')
            elif typ == 'turn.completed':
                completed = True
            elif typ in ('error', 'turn.failed'):
                failed = True
                error = event.get('error')
                message = error.get('message') if isinstance(error, dict) else event.get('message')
                if message and not (runtime and runtime.last_error):
                    say('Error: ' + redact(str(message), secrets))
    except KeyboardInterrupt:
        forced_rc = 130
        if runtime:
            runtime.cancel.set()
        say('Interrupted. Local agent stopped; submitted remote jobs may continue.')
    except BrokenPipeError:
        failed = True
    finally:
        stopping.set()
        if forced_rc is not None or failed:
            _stop_process(process)
        try:
            rc = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            rc = 1
        for reader in readers:
            reader.join(timeout=1)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe and not pipe.closed:
                pipe.close()
    if rc or failed:
        for line in list(stderr_lines)[-12:]:
            if line.strip():
                say(line.rstrip())
    if runtime and runtime.last_error:
        failed = True
        say('JV adapter: ' + redact(runtime.last_error, secrets))
    if forced_rc is not None:
        return forced_rc, current
    if rc == 0 and not failed and (not completed or not saw_message):
        say('Agent ended without a confirmed final answer. This is not reported as success.')
        failed = True
    rc = 128 - rc if rc < 0 else rc
    return (1 if failed and rc == 0 else rc), current


def _workspace_check(path):
    path = path.resolve()
    user_home = Path.home().resolve()
    if path == Path('/') or path == user_home or path == APP_ROOT or path in APP_ROOT.parents:
        raise JvError('Choose a dedicated project directory, not your home, filesystem root, or the JV CLI installation')
    # JV CLI provides a private CODEX_HOME, so ~/.codex is neither loaded nor
    # modified. Still reject configuration belonging to the selected project.
    for parent in (path, *path.parents):
        if parent == user_home or parent == Path('/'):
            continue
        if (parent / '.codex/config.toml').exists():
            raise JvError(f'Existing agent project config found at {parent / ".codex/config.toml"}. Review it and use a clean test copy; this release does not load custom project engine config')
    return path


def _session_id():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]


def _session_directory(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise JvError('Invalid JV session ID')
    return no_symlink_path(STATE_DIR / 'runs' / value)


def _run_session(prompt=None, *, resume=None, read_only=False, allow_network=False, json_mode=False):
    workspace = _workspace_check(Path.cwd())
    if read_only and allow_network:
        raise JvError('--allow-network is available only in workspace-write mode')
    engine = _find_engine()
    if not engine:
        raise JvError('Local agent engine is missing. From the JV CLI folder run ./install.sh')
    actual = _version_of_engine(engine)
    if actual != ENGINE_VERSION:
        raise JvError(f'Engine {actual} is not the pinned {ENGINE_VERSION}; run ./install.sh. No automatic downgrade is performed at runtime')
    base, user = _resolve_account()
    sid = resume or _session_id()
    session_dir = _session_directory(sid)
    metadata = read_private_json(session_dir / 'session.json') if resume else {}
    if resume and not metadata:
        raise JvError('Saved JV session was not found')
    if resume and (metadata.get('workspace') != str(workspace) or metadata.get('username') != user or metadata.get('base_url') != base):
        raise JvError('Resume must use the same project directory, API origin and username as the saved session')
    private_dir(session_dir)
    install_fd = os.open(STATE_DIR / 'install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(install_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(install_fd)
        raise JvError('Installation/update is in progress; do not start a session yet') from None
    try:
        lock_fd = os.open(session_dir / 'session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except BaseException:
        os.close(install_fd)
        raise
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JvError('This JV session is already open in another terminal') from None
        max_requests = int(positive_number(os.environ.get('JVCLI_MAX_REQUESTS', '40'), 'JVCLI_MAX_REQUESTS', 500))
        turn_timeout = positive_number(os.environ.get('JVCLI_TURN_TIMEOUT', '3600'), 'JVCLI_TURN_TIMEOUT')
        client, user = _login_client(user, base)
        runtime = AdapterRuntime(client, max_requests=max_requests)
        thread_id = metadata.get('thread_id')
        metadata = {'session_id': sid, 'workspace': str(workspace), 'username': user, 'base_url': base,
                    'thread_id': thread_id, 'created_at': metadata.get('created_at', datetime.datetime.now(datetime.timezone.utc).isoformat())}
        try:
            port = runtime.start()
            overrides = _write_engine_config(session_dir, port, read_only, allow_network)
            atomic_write(session_dir / 'session.json', json.dumps(metadata, indent=2) + '\n')
            say(f'JV CLI {VERSION}\nWorkspace: {workspace}\nSession: {sid}\nSandbox: {"read-only" if read_only else "workspace-write"}; tool network: {"enabled" if allow_network else "disabled"}')
            say('Only use trusted projects. The selected workspace may be changed; installation isolation is not a VM.')
            if prompt is None:
                say('Type /help for commands.')
            while True:
                one_shot = prompt is not None
                if one_shot:
                    task = prompt
                else:
                    try:
                        print('\n> ', end='', file=sys.stderr, flush=True)
                        task = input().strip()
                    except (EOFError, KeyboardInterrupt):
                        say('')
                        return 0
                    if not task:
                        continue
                    if task in ('/exit', '/quit'):
                        return 0
                    if task == '/help':
                        say('/new: start a new agent thread\n/status: show session and last job\n/exit: sign out and exit\nCtrl+C during a turn: stop local work and exit')
                        continue
                    if task == '/status':
                        say(f'Session: {sid}\nThread: {thread_id or "new"}\nState: {runtime.status}\nLast JV job: {runtime.last_job_id or "none"}')
                        continue
                    if task == '/new':
                        if runtime.lock.locked():
                            say('Previous request is still stopping. Exit and restart before submitting another task.')
                        else:
                            thread_id = None
                            say('New agent thread. Saved earlier engine histories are retained locally.')
                        continue
                    if task.startswith('/'):
                        say('Unknown command; use /help')
                        continue
                runtime.begin_turn()
                rc, new_thread = _run_engine(engine, task, thread_id, session_dir=session_dir, overrides=overrides,
                    runtime=runtime, json_mode=json_mode,
                    turn_timeout=turn_timeout)
                if new_thread:
                    thread_id = new_thread
                    metadata['thread_id'] = thread_id
                metadata['last_job_id'] = runtime.last_job_id
                metadata['last_exit_code'] = rc
                metadata['model_requests'] = runtime.requests
                metadata['response_repairs'] = runtime.response_repairs
                atomic_write(session_dir / 'session.json', json.dumps(metadata, indent=2) + '\n')
                if one_shot or rc in (124, 130):
                    return rc
                if rc:
                    say('Turn stopped. Check /status and the reported JV job before resubmitting a task.')
        finally:
            runtime.close()
            _logout(client)
    finally:
        os.close(lock_fd)
        os.close(install_fd)


def command_login(args):
    client, user = _login_client(args.username, args.base_url)
    try:
        say(f'Credentials verified for {user}. Username/origin saved; password and bearer token are not saved.')
    finally:
        _logout(client)
    return 0


def command_doctor(json_mode=False):
    data = {'version': VERSION, 'python': sys.version.split()[0], 'install_root': str(APP_ROOT),
            'state_dir': str(STATE_DIR), 'pinned_engine': ENGINE_VERSION, 'checks': {}}
    try:
        _ensure_state()
        data['checks']['private_state'] = (STATE_DIR.stat().st_mode & 0o077) == 0
        config = _load_disk_config()
        data['base_url'] = validate_base_url(os.environ.get('JV_API_BASE_URL') or config.get('base_url') or DEFAULT_BASE_URL)
        data['username'] = os.environ.get('JV_API_USERNAME') or config.get('username') or 'NOT CONFIGURED'
        data['checks']['python_3_10_or_later'] = sys.version_info >= (3, 10)
        engine = _find_engine()
        data['engine_version'] = _version_of_engine(engine) if engine else 'NOT INSTALLED'
        data['checks']['engine_version'] = data['engine_version'] == ENGINE_VERSION
        if engine:
            for name, args in [('exec_help', ['exec', '--help']), ('resume_help', ['exec', 'resume', '--help'])]:
                p = subprocess.run([engine, *args], capture_output=True, text=True, timeout=10, env=_diagnostic_env(), stdin=subprocess.DEVNULL)
                data['checks'][name] = p.returncode == 0 and '--json' in p.stdout
    except (JvError, OSError, subprocess.SubprocessError) as exc:
        data['error'] = str(exc)
        data['checks']['installation'] = False
    data['ok'] = all(data['checks'].values())
    data['live_api_tested'] = False
    data['sandbox_execution_tested'] = False
    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        print(f'JV CLI {VERSION}\nPython: {data["python"]}\nAgent engine: {data.get("engine_version", "unavailable")}\nJV API: {data.get("base_url", "unconfigured")}\nUsername: {data.get("username", "unconfigured")}\nInstall root: {APP_ROOT}\nState: {STATE_DIR}')
        for key, value in data['checks'].items():
            print(f'{"PASS" if value else "FAIL"}: {key}')
        if 'error' in data:
            say(data['error'])
        print('Doctor does not contact the live API or prove sandbox enforcement. Run the acceptance checks before rollout.')
    return 0 if data['ok'] else 1


def command_raw(args):
    client, _ = _login_client()
    try:
        if args.command == 'ask':
            job = client.submit_job(' '.join(args.prompt), conversation_id=args.conversation_id, file_paths=args.file)
            say(f'Created JV job {job["id"]}; conversation {job["conversation_id"]}')
        else:
            job = client.get_job(args.job_id)
        if job['status'] not in ('succeeded', 'failed'):
            job = client.wait_for_job(job['id'], conversation_id=job['conversation_id'])
        downloads = client.download_response_files(job, Path(args.download_dir)) if args.download_dir and job['status'] == 'succeeded' else []
        if args.json:
            # Whitelist public fields; do not print arbitrary server response keys.
            safe = {k: job.get(k) for k in ('id', 'conversation_id', 'status', 'answer')}
            safe['downloaded_files'] = [str(p) for p in downloads]
            print(json.dumps(redact_data(safe, (client._token or '',)), ensure_ascii=False, indent=2))
        elif job['status'] == 'succeeded':
            print(terminal_text(redact(job.get('answer') or '(No text answer)', (client._token or '',))))
            say(f'Job: {job["id"]}; conversation: {job["conversation_id"]}')
            for path in downloads:
                say(f'Downloaded: {path}')
        else:
            say(f'JV job {job["id"]} failed')
        return 0 if job['status'] == 'succeeded' else 1
    finally:
        _logout(client)


def command_sessions():
    directory = STATE_DIR / 'runs'
    if not directory.exists():
        print('No saved sessions')
        return 0
    for path in sorted(directory.glob('*/session.json')):
        value = read_private_json(path)
        print(terminal_text(f'{value.get("session_id", path.parent.name)}  {value.get("workspace", "?")}'))
    return 0


def command_uninstall(args):
    command = [sys.executable, '-B', str(APP_ROOT / 'scripts/manage.py'), 'uninstall']
    if args.keep_state:
        command.append('--keep-state')
    if args.yes:
        command.append('--yes')
    return subprocess.call(command)


def _parser():
    parser = argparse.ArgumentParser(prog='jvcli', description='JV CLI coding agent. No password is stored.')
    parser.add_argument('--version', action='version', version='JV CLI ' + VERSION)
    parser.add_argument('--read-only', action='store_true', help='Deny model tool writes')
    parser.add_argument('--allow-network', action='store_true', help='Explicitly allow tool networking; does not grant system-wide writes')
    subs = parser.add_subparsers(dest='command')
    login = subs.add_parser('login', help='Verify credentials and save username/API origin only')
    login.add_argument('--username')
    login.add_argument('--base-url')
    auth = subs.add_parser('auth')
    auth.add_argument('action', choices=['status'])
    subs.add_parser('logout', help='Forget saved account settings; active sessions must be exited separately')
    doctor = subs.add_parser('doctor')
    doctor.add_argument('--json', action='store_true')
    subs.add_parser('self-test', help='Run offline mock/unit regression tests')
    subs.add_parser('sessions', help='List saved local JV sessions')
    uninstall = subs.add_parser('uninstall', help='Safely remove the per-user JV CLI installation')
    uninstall.add_argument('--keep-state', action='store_true', help='Preserve local account settings and sessions')
    uninstall.add_argument('--yes', action='store_true', help='Confirm the displayed removal warning noninteractively')
    for command in ('exec', 'resume'):
        sub = subs.add_parser(command)
        if command == 'resume':
            sub.add_argument('session_id')
        sub.add_argument('prompt', nargs='+' if command == 'exec' else '*')
        sub.add_argument('--read-only', action='store_true', default=argparse.SUPPRESS)
        sub.add_argument('--allow-network', action='store_true', default=argparse.SUPPRESS)
        sub.add_argument('--json', action='store_true', help='Output agent events as JSONL, diagnostics on stderr')
    for command in ('ask', 'job'):
        sub = subs.add_parser(command, help='Direct JV API request; does not execute coding tools')
        if command == 'ask':
            sub.add_argument('prompt', nargs='+')
            sub.add_argument('--conversation-id')
            sub.add_argument('--file', action='append', default=[])
        else:
            sub.add_argument('job_id')
        sub.add_argument('--download-dir')
        sub.add_argument('--json', action='store_true')
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Preserve the earlier jvcli "a task" shorthand without treating mistyped
    # option flags as an instruction sent to the LLM.
    known = {'exec', 'resume', 'login', 'logout', 'auth', 'doctor', 'self-test', 'sessions', 'uninstall', 'ask', 'job'}
    if argv and not argv[0].startswith('-') and argv[0] not in known:
        argv = ['exec', *argv]
    args = _parser().parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise JvError('Python 3.10 or later is required')
        if args.command == 'doctor':
            return command_doctor(args.json)
        if args.command == 'self-test':
            env = os.environ.copy()
            for key in ('JV_API_PASSWORD', 'JV_API_USERNAME', 'JV_API_BASE_URL', 'JVCLI_CODEX_BIN'):
                env.pop(key, None)
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            return subprocess.call([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(APP_ROOT / 'tests'), '-v'], cwd=APP_ROOT, env=env)
        if args.command == 'auth':
            config = _load_disk_config()
            print(f'API: {config.get("base_url", DEFAULT_BASE_URL)}\nUsername: {config.get("username", "NOT CONFIGURED")}\nPassword: not stored\nLogin command: verifies and immediately signs out\nActive tokens: memory-only in running sessions')
            return 0
        if args.command == 'logout':
            _save_disk_config({})
            say('Saved account settings cleared. Exit other running JV CLI sessions to revoke their tokens.')
            return 0
        if args.command == 'login':
            return command_login(args)
        if args.command == 'sessions':
            return command_sessions()
        if args.command == 'uninstall':
            return command_uninstall(args)
        _ensure_state()
        if args.command in ('ask', 'job'):
            return command_raw(args)
        prompt = ' '.join(args.prompt) if getattr(args, 'prompt', None) else None
        if prompt is None and not sys.stdin.isatty():
            raise JvError('Interactive mode requires a terminal; use jvcli exec "your task" for automation')
        return _run_session(prompt, resume=getattr(args, 'session_id', None), read_only=args.read_only,
                            allow_network=args.allow_network, json_mode=getattr(args, 'json', False))
    except KeyboardInterrupt:
        say('Interrupted. A submitted remote job may continue.')
        return 130
    except (JvError, OSError, ValueError) as exc:
        say('Error: ' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
