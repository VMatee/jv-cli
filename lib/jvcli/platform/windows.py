"""Native Windows handoff contracts, not an implementation of Windows support.

Never substitute chmod, unlocked files, or parent-only kill for these operations.
See docs/WINDOWS_NATIVE_HANDOFF.md for acceptance gates and native API references.
"""
from __future__ import annotations

import contextlib

from .common import PlatformUnavailableError, windows_state_path


def unavailable(operation):
    raise PlatformUnavailableError(
        f"Native Windows {operation} is not implemented; "
        "continue feature/windows-native using docs/WINDOWS_NATIVE_HANDOFF.md"
    )


def state_directory(app_root, environ):
    return windows_state_path(environ)


def no_symlink_path(path):
    """Must reject unsafe junctions/reparse points and verify native containment."""
    unavailable("path security")


def private_dir(path):
    """Create/verify a user-private ACL before any secret or state is written."""
    unavailable("private directory ACLs")


def atomic_write(path, text, mode=0o600):
    """Private create, safe atomic replacement, mode-to-ACL policy, cleanup."""
    unavailable("private atomic file writes")


def open_private_read(path):
    """Return a Python-compatible readable FD after handle/reparse checks."""
    unavailable("private file reads")


def open_lock(path, *, create=True):
    """Return an owned opaque handle; create=False must never create a file."""
    unavailable("session/install lock opening")


def lock_file(handle, *, shared=False):
    """Nonblocking shared/exclusive lock; contention raises BlockingIOError."""
    unavailable("session/install locking")


def close_lock(handle):
    """Release only this owner's handle; process death must release ownership."""
    unavailable("session/install lock release")


def find_engine(runtime, explicit=None):
    """Discover a verified native executable/argv launcher, never a shell shim."""
    unavailable("engine discovery")


def spawn_engine(command, env):
    """Argv spawn, UTF-8 pipes, prompt on stdin, owned child-tree containment."""
    unavailable("owned process creation")


def stop_process(process):
    """Bounded cleanup of the owned local tree, including orphaned children."""
    unavailable("owned process-tree cancellation")


def require_terminal():
    unavailable("interactive console input")


def require_bridge_io():
    unavailable("bounded bridge pipe transport")


@contextlib.contextmanager
def deadline(seconds, timeout_error):
    """No timed-out auth/logout owner may survive or mutate bridge state later."""
    unavailable("bridge operation deadlines")
    yield
