"""Local file, JSON and terminal hygiene. No third-party dependencies."""
from __future__ import annotations

import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any

from .platform import get_backend


class JvError(RuntimeError):
    """User-facing error: messages must not contain secrets or raw HTTP bodies."""


class ProtocolError(JvError):
    pass


class SubmissionUncertain(JvError):
    failure_code = "remote_submission_uncertain"


class UncertainToolSideEffect(ProtocolError):
    """A published action lacks a reconciled result; never publish it again."""

    failure_code = "uncertain_tool_side_effect"


class RemoteInferenceError(JvError):
    """Terminal remote failure, with an allowlisted local classification."""

    def __init__(self, failure_code: str, message: str):
        self.failure_code = failure_code
        super().__init__(message)


class Cancelled(JvError):
    pass


def strict_json(text: str | bytes) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON number")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def positive_number(value: Any, name: str, maximum: float = 86400) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise JvError(f"{name} must be a positive finite number") from None
    if isinstance(value, bool) or not math.isfinite(number) or not 0 < number <= maximum:
        raise JvError(f"{name} must be greater than 0 and at most {maximum:g}")
    return number


def no_symlink_path(path: Path) -> Path:
    """Reject existing symlink components; retain a lexical absolute path."""
    return get_backend().no_symlink_path(path)


def private_dir(path: Path) -> Path:
    return get_backend().private_dir(path)


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    return get_backend().atomic_write(path, text, mode)


def read_private_json(path: Path, *, max_bytes: int = 1024 * 1024) -> dict:
    path = no_symlink_path(path)
    try:
        fd = get_backend().open_private_read(path)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, "rb") as handle:
        meta = os.fstat(handle.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > max_bytes:
            raise JvError(f"Invalid state file: {path}")
        try:
            value = strict_json(handle.read(max_bytes + 1))
        except (ValueError, UnicodeError, RecursionError):
            raise JvError(f"Invalid JSON in {path}; preserve it for recovery rather than overwriting it") from None
    if not isinstance(value, dict):
        raise JvError(f"Expected a JSON object in {path}")
    return value


# Strip ANSI/OSC and other terminal controls from model/server/tool text.
_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def terminal_text(value: Any) -> str:
    return _CONTROLS.sub("", _ANSI.sub("", str(value)))


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    text = re.sub(r'data:[^\s,;]+;base64,[A-Za-z0-9+/=]+', '[REDACTED IMAGE DATA]', text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", r"\1[REDACTED]", text)
    return terminal_text(text)


def redact_data(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [redact_data(item, secrets) for item in value]
    if isinstance(value, dict):
        return {redact(str(key), secrets): redact_data(item, secrets) for key, item in value.items()}
    return value
