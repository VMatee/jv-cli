"""Process-isolated bridge authentication; only the caller installs results."""
import json
import msvcrt
import os
from pathlib import Path
import sys
import subprocess
import threading
import time

from ._windows_process import OwnedProcess
from ._windows_pipe import PipeWorker
from ._windows_engine import isolated_env
from ..safety import JvError, strict_json


class AuthCleanupError(JvError):
    """Fatal: the bridge must not accept further operations."""


def operation(client, operation, seconds, timeout_error, *, root, username=None,
              password=None, executable=None, worker=None):
    """Internal executable/worker injection is for native offline fixtures only.

    No callable/client is shared with the child. Parent state is changed only
    after successful exit, joined I/O, validated result, and the final deadline.
    """
    end = time.monotonic() + seconds
    request = {'operation': operation, 'base': client.base_url,
               'timeout': min(seconds, client.config.request_timeout)}
    if operation == 'login':
        if client._token is not None:
            raise JvError('Already signed in')
        request.update(username=username, password=password)
    elif operation == 'logout':
        request['token'] = client._token
        client._token = None  # Relinquish local ownership before remote revocation.
        if request['token'] is None:
            return
    else:
        raise ValueError('Unsupported authentication operation')
    payload = json.dumps(request, ensure_ascii=True)
    if len(payload.encode()) > 65536:
        raise JvError('Authentication request exceeds its limit')
    env = isolated_env(root)
    env['PYTHONHOME'] = sys.base_prefix
    command = [executable or sys.executable, '-s', '-B',
               str(worker or Path(__file__).with_name('_windows_auth_worker.py'))]
    read_fd, write_fd = os.pipe()
    process = reader = sender = None
    errors = []
    expired = threading.Event()
    result = bytearray()
    try:
        os.set_inheritable(write_fd, True)
        handle = msvcrt.get_osfhandle(write_fd)
        process = OwnedProcess([*command, str(handle)], env, inherited_handles=(handle,))
        os.close(write_fd)
        write_fd = None
        reader = PipeWorker(read_fd)
        def communicate():
            try:
                stdout, stderr = process.communicate(payload, timeout=max(.001, end - time.monotonic()))
                if stdout or stderr or process.returncode:
                    errors.append(True)
            except subprocess.TimeoutExpired:
                expired.set()
            except Exception:
                errors.append(True)
        sender = threading.Thread(target=communicate, name='bridge-auth-io', daemon=True)
        sender.start()
        while True:
            if time.monotonic() >= end:
                raise timeout_error()
            chunk = reader.read()
            if chunk == b'':
                break
            if chunk:
                result.extend(chunk)
                if len(result) > 32768:
                    raise JvError('Invalid authentication result')
        sender.join(max(0, end - time.monotonic()))
        if sender.is_alive() or expired.is_set() or time.monotonic() >= end:
            raise timeout_error()
        if errors:
            raise JvError('Authentication operation failed')
        response = strict_json(result)
        if operation == 'login':
            token = response.get('token') if isinstance(response, dict) else None
            if (not isinstance(token, str) or not 1 <= len(token) <= 16384
                    or not all(33 <= ord(c) <= 126 for c in token)):
                raise JvError('Invalid authentication result')
        elif response != {'ok': True}:
            raise JvError('Invalid authentication result')
    finally:
        cleanup_failed = False
        try:
            if process:
                process.terminate()
                process.wait(5)
        except Exception:
            cleanup_failed = True
        try:
            if reader:
                reader.close()
        except Exception:
            cleanup_failed = True
        if sender:
            sender.join(6)
            cleanup_failed |= sender.is_alive()
        elif process:
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        if not (reader and reader.thread.is_alive()):
            os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if cleanup_failed:
            raise AuthCleanupError('Authentication worker cleanup failed') from None
    if time.monotonic() >= end:
        raise timeout_error()
    if operation == 'login':
        client._token = token
