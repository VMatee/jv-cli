"""Pure Windows naming contracts, usable in Linux preparation tests.

Lexical validation is not filesystem containment or an ACL/reparse-point check.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
import re

from ..safety import JvError


class PlatformUnavailableError(JvError):
    """An OS operation has no validated native implementation yet."""


def windows_state_path(environ) -> PureWindowsPath:
    override = environ.get("JVCLI_HOME")
    base = override or environ.get("LOCALAPPDATA")
    if not base:
        raise JvError("Windows state requires LOCALAPPDATA or an absolute JVCLI_HOME")
    path = PureWindowsPath(base)
    if not path.is_absolute() or str(path).startswith(("\\\\?\\", "\\\\.\\")):
        raise JvError("Windows state requires a fully qualified drive or UNC path")
    # Avoid ambiguous names, device files, and alternate data streams in state.
    for part in path.parts[1:]:
        stem = part.split(".", 1)[0].rstrip(" ").upper()
        if (part in {".", ".."} or part.endswith((" ", "."))
                or any(c in part for c in '<>:"|?*')
                or any(ord(c) < 32 for c in part)
                or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]", stem)):
            raise JvError("Windows state contains an unsupported filename component")
    return path if override else path / "JV" / "jv-cli"


def native_executable_name(name: str, *, platform_name: str) -> str:
    """Name a native executable; a .cmd shim is not a native launcher."""
    if platform_name == "nt":
        return name if name.lower().endswith(".exe") else name + ".exe"
    if platform_name == "posix":
        return name
    raise JvError(f"Unsupported JV CLI platform: {platform_name}")
