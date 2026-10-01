"""Pinned native package discovery and explicit Windows child environments."""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path
import platform
import struct

from . import _windows_fs as fs
from ..safety import JvError, strict_json

TARGET = "x86_64-pc-windows-msvc"


def verify_executable(path):
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise JvError("The pinned Windows runtime requires AMD64")
    path = fs.native_path(path)
    if path.suffix.lower() != ".exe":
        raise JvError("Windows engine must be a native executable, not a shell shim")
    with os.fdopen(fs.open_public_read(path), "rb") as stream:
        dos = stream.read(64)
        if len(dos) != 64 or dos[:2] != b"MZ":
            raise JvError("Windows engine is not a PE executable")
        offset = struct.unpack_from("<I", dos, 60)[0]
        if not 64 <= offset <= 1024 * 1024:
            raise JvError("Windows engine has an invalid PE header")
        stream.seek(offset)
        header = stream.read(26)
        if (len(header) != 26 or header[:4] != b"PE\0\0"
                or struct.unpack_from("<H", header, 4)[0] != 0x8664
                or struct.unpack_from("<H", header, 24)[0] != 0x20B
                or not struct.unpack_from("<H", header, 22)[0] & 2
                or struct.unpack_from("<H", header, 22)[0] & 0x2000):
            raise JvError("Windows engine requires an AMD64 PE32+ executable")
    return path


def _package(path, expected_version):
    path = verify_executable(path)
    if path.name.lower() != "codex.exe" or path.parent.name.lower() != "bin":
        raise JvError("Windows engine must use the verified native package layout")
    root = path.parent.parent
    with os.fdopen(fs.open_public_read(root / "codex-package.json"), "rb") as stream:
        data = stream.read(16385)
    try:
        metadata = strict_json(data)
    except (ValueError, UnicodeError, RecursionError):
        raise JvError("Invalid Windows engine package metadata") from None
    expected = {"layoutVersion": 1, "version": expected_version, "target": TARGET,
                "variant": "codex", "entrypoint": "bin/codex.exe",
                "resourcesDir": "codex-resources", "pathDir": "codex-path"}
    if len(data) > 16384 or metadata != expected or type(metadata.get("layoutVersion")) is not int:
        raise JvError("Windows engine package does not match the pinned version/layout")
    # Helpers are part of the same native package; don't silently launch a partial
    # install that could resolve a similarly named program through the user's PATH.
    for relative in ("codex-resources/codex-command-runner.exe",
                     "codex-resources/codex-windows-sandbox-setup.exe",
                     "codex-path/rg.exe"):
        verify_executable(root / relative)
    return str(path)


def find_engine(runtime, explicit=None):
    from ..cli import ENGINE_VERSION
    if explicit:
        return _package(Path(explicit), ENGINE_VERSION)
    runtime = Path(runtime)
    for root in (runtime / "node_modules/@openai/codex-win32-x64",
                 runtime / "node_modules/@openai/codex"):
        executable = root / "vendor" / TARGET / "bin/codex.exe"
        try:
            return _package(executable, ENGINE_VERSION)
        except FileNotFoundError:
            # A missing candidate is normal; incomplete existing packages fail.
            if executable.exists():
                raise JvError("Windows engine package is incomplete") from None
    return None


def minimal_env():
    # GetWindowsDirectoryW avoids trusting parent SYSTEMROOT/WINDIR/PATH overrides.
    get_windows = fs._api(fs.K, "GetWindowsDirectoryW", fs.W.UINT, fs.W.LPWSTR, fs.W.UINT)
    buffer = C.create_unicode_buffer(32768)
    count = fs._check(get_windows(buffer, len(buffer)))
    if count >= len(buffer):
        raise JvError("Windows system directory path exceeds the supported limit")
    system = Path(buffer.value)
    return {
        "SYSTEMROOT": str(system), "WINDIR": str(system),
        "COMSPEC": str(system / "System32/cmd.exe"),
        "PATH": os.pathsep.join(map(str, (system / "System32", system,
                                         system / "System32/WindowsPowerShell/v1.0"))),
        "PATHEXT": ".EXE", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1",
    }


def isolated_env(root, *, adapter_key=None):
    root = fs.private_dir(root)
    home = fs.private_dir(root / "tool-home")
    engine = fs.private_dir(root / "engine")
    tmp = fs.private_dir(root / "tmp")
    appdata = fs.private_dir(home / "AppData/Roaming")
    local = fs.private_dir(home / "AppData/Local")
    env = minimal_env()
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(appdata),
               LOCALAPPDATA=str(local), TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp),
               CODEX_HOME=str(engine), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_CACHE_HOME=str(home / ".cache"),
               PIP_REQUIRE_VIRTUALENV="true", PIP_DISABLE_PIP_VERSION_CHECK="1")
    if adapter_key:
        # The trusted engine authenticates to the local adapter. This explicit
        # key never comes from the parent environment and is excluded from tools.
        env["JVCLI_ADAPTER_KEY"] = adapter_key
    return env


def tool_environment(session_dir):
    env = isolated_env(session_dir)
    # Give tools their own empty Codex home, separate from the engine's config.
    env["CODEX_HOME"] = str(fs.private_dir(Path(env["USERPROFILE"]) / ".codex"))
    return {"inherit": "none", "ignore_default_excludes": False,
            "experimental_use_profile": False, "set": env}
