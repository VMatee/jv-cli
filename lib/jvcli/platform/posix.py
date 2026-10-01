"""Existing Linux operations extracted without changing their OS semantics."""
from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import tempfile

from ..safety import JvError


def state_directory(app_root, environ):
    return Path(environ.get("JVCLI_HOME", str(app_root / ".state"))).expanduser().absolute()


def no_symlink_path(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise JvError(f"Refusing a symbolic-link path: {part}")
    return path


def private_dir(path: Path) -> Path:
    path = no_symlink_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise JvError(f"Not a directory: {path}")
    path.chmod(0o700)
    return path


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path = no_symlink_path(path)
    private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".jv-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def open_private_read(path):
    return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)


def open_lock(path, *, create=True):
    # The caller checks its containing private directory before reaching here.
    return os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)


def lock_file(handle, *, shared=False):
    fcntl.flock(handle, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)


def close_lock(handle):
    os.close(handle)


def find_engine(runtime, explicit=None):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise JvError("JVCLI_CODEX_BIN does not point to an executable file")
        return str(path)
    for path in (runtime / "node_modules/.bin/codex", runtime / "bin/codex"):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def spawn_engine(command, env):
    return subprocess.Popen(
        command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, shell=False, start_new_session=True,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )


def stop_process(process):
    # Cancellation/failure only: the parent may exit before its children.
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


def require_terminal():
    """POSIX palette uses termios/tty, imported only when a TTY is used."""


def require_bridge_io():
    """The current bounded bridge pipes use POSIX select/nonblocking FDs."""


@contextlib.contextmanager
def deadline(seconds, timeout_error):
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise timeout_error()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
