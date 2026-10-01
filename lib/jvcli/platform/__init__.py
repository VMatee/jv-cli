"""Small native OS boundary; shared protocol/business logic stays in jvcli.

Backends are loaded lazily so importing JV CLI on Windows needs no POSIX modules.
Windows security/execution operations deliberately fail until implemented there.
"""
from __future__ import annotations

import os


def get_backend(platform_name: str | None = None):
    name = os.name if platform_name is None else platform_name
    if name == "posix":
        from . import posix
        return posix
    if name == "nt":
        from . import windows
        return windows
    from ..safety import JvError
    raise JvError(f"Unsupported JV CLI platform: {name}")


def state_directory(app_root, environ=None, *, platform_name=None):
    """Select a location without creating it or asserting that it is private."""
    return get_backend(platform_name).state_directory(
        app_root, os.environ if environ is None else environ
    )
