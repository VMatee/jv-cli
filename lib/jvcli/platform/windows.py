"""Native Windows backend; unfinished execution operations remain fail-closed.

Never substitute chmod, unlocked files, or parent-only kill for these operations.
See docs/WINDOWS_NATIVE_HANDOFF.md for acceptance gates and native API references.
"""
from __future__ import annotations

import contextlib
import os

from .common import PlatformUnavailableError, windows_state_path


def unavailable(operation):
    raise PlatformUnavailableError(
        f"Native Windows {operation} is not implemented; "
        "continue feature/windows-native using docs/WINDOWS_NATIVE_HANDOFF.md"
    )


def state_directory(app_root, environ):
    return windows_state_path(environ)


def _filesystem():
    if os.name != "nt":
        unavailable("filesystem operations on a non-Windows host")
    from . import _windows_fs
    return _windows_fs


def no_symlink_path(path):
    return _filesystem().no_symlink_path(path)


def private_dir(path):
    return _filesystem().private_dir(path)


def atomic_write(path, text, mode=0o600):
    return _filesystem().atomic_write(path, text, mode)


def durable_atomic_write(path, text):
    return _filesystem().atomic_write(path, text, durable=True)


def open_private_read(path):
    return _filesystem().open_private_read(path)


def open_lock(path, *, create=True):
    return _filesystem().open_lock(path, create=create)


def lock_file(handle, *, shared=False):
    return _filesystem().lock_file(handle, shared=shared)


def close_lock(handle):
    return _filesystem().close_lock(handle)


def find_engine(runtime, explicit=None):
    _filesystem()
    from . import _windows_engine
    return _windows_engine.find_engine(runtime, explicit)


def spawn_engine(command, env):
    _filesystem()
    from . import _windows_process
    return _windows_process.spawn_engine(command, env)


def stop_process(process):
    _filesystem()
    from . import _windows_process
    return _windows_process.stop_process(process)


def minimal_env():
    _filesystem()
    from . import _windows_engine
    return _windows_engine.minimal_env()


def isolated_env(root, *, adapter_key=None):
    _filesystem()
    from . import _windows_engine
    return _windows_engine.isolated_env(root, adapter_key=adapter_key)


def tool_environment(root):
    _filesystem()
    from . import _windows_engine
    return _windows_engine.tool_environment(root)


def require_terminal():
    unavailable("interactive console input")


def require_bridge_io():
    unavailable("secure bridge sessions (explicit --execution-mode trusted-host is required)")


@contextlib.contextmanager
def deadline(seconds, timeout_error):
    """No timed-out auth/logout owner may survive or mutate bridge state later."""
    unavailable("bridge operation deadlines")
    yield
