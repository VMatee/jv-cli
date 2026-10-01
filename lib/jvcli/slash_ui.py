"""Small terminal command palette for interactive JV CLI sessions.

Only slash commands use the palette. Ordinary tasks still use the terminal's
readline editor, including its Unicode input and paste handling.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from difflib import SequenceMatcher
import os
import select
import shutil
import sys
import unicodedata

from .platform import get_backend


@dataclass(frozen=True)
class SlashCommand:
    name: str
    action: str
    description: str


COMMANDS = (
    SlashCommand("/help", "help", "ดูคำสั่งทั้งหมด"),
    SlashCommand("/status", "status", "ดูสถานะเซสชันและงานล่าสุด"),
    SlashCommand("/permissions", "permissions", "ดูสิทธิ์ไฟล์และเครือข่าย"),
    SlashCommand("/permission", "permissions", "ชื่อย่อของ /permissions"),
    SlashCommand("/new", "new", "เริ่มหัวข้อใหม่ในเซสชันนี้"),
    SlashCommand("/exit", "exit", "ปิดเซสชัน แต่เก็บบัญชีที่บันทึกไว้"),
    SlashCommand("/quit", "exit", "ชื่อย่อของ /exit"),
    SlashCommand("/logout", "logout", "ออกและลบบัญชีที่บันทึกไว้"),
)
_ACTIONS = {command.name: command.action for command in COMMANDS}
_PALETTE_LIMIT = len(COMMANDS)


def command_action(value: str) -> str | None:
    """Resolve only an exact English slash command; never guess an action."""
    return _ACTIONS.get(value.strip().casefold())


def suggestions(value: str, limit: int = _PALETTE_LIMIT) -> tuple[SlashCommand, ...]:
    query = value.casefold()
    if not query.startswith("/") or any(ch.isspace() for ch in query) or limit < 1:
        return ()
    prefix = tuple(command for command in COMMANDS if command.name.startswith(query))
    if prefix:
        return prefix[:limit]
    scored = sorted(
        (
            (SequenceMatcher(None, query, command.name).ratio(), index, command)
            for index, command in enumerate(COMMANDS)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return tuple(item[2] for item in scored if item[0] >= 0.55)[:limit]


def unknown_command_message(value: str) -> str:
    matches = suggestions(value, 1)
    if matches:
        return f"ไม่รู้จักคำสั่งนี้ ลอง {matches[0].name} หรือ /help"
    return "ไม่รู้จักคำสั่งนี้ ใช้ /help เพื่อดูคำสั่ง"


def help_text() -> str:
    return (
        "/help: ดูคำสั่งทั้งหมด\n"
        "/status: ดูสถานะเซสชันและงานล่าสุด\n"
        "/permissions (or /permission): ดูสิทธิ์ไฟล์และเครือข่ายของเซสชัน\n"
        "/new: เริ่มหัวข้อใหม่\n"
        "/exit (or /quit): ปิดเซสชันนี้ โดยเก็บบัญชีที่บันทึกไว้\n"
        "/logout: ปิดเซสชันและลบบัญชีที่บันทึกไว้\n"
        "พิมพ์ / เพื่อดูคำสั่ง กด Tab เพื่อเติมคำสั่ง หรือใช้ ↑↓ แล้ว Enter\n"
        "พิมพ์คำถามภาษาไทยได้ตามปกติ; Ctrl+C ระหว่างงานจะหยุดการรอในเครื่อง"
    )


def _cell_width(value: str) -> int:
    width = 0
    for char in value:
        if unicodedata.combining(char) or unicodedata.category(char) in {"Cf", "Me"}:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _fit(value: str, width: int) -> str:
    if _cell_width(value) <= width:
        return value
    if width < 2:
        return ""
    result = ""
    for char in value:
        if _cell_width(result + char) > width - 1:
            break
        result += char
    return result + "…"


def _read_key(fd: int) -> tuple[str, str]:
    first = os.read(fd, 1)
    if not first:
        return "eof", ""
    if first == b"\x1b":
        if not select.select([fd], [], [], 0.04)[0]:
            return "escape", ""
        second = os.read(fd, 1)
        if second not in {b"[", b"O"}:
            return "escape", ""
        sequence = bytearray()
        for _ in range(8):
            if not select.select([fd], [], [], 0.04)[0]:
                break
            char = os.read(fd, 1)
            if not char:
                break
            sequence.extend(char)
            if 0x40 <= char[0] <= 0x7E:
                break
        name = {
            b"A": "up",
            b"B": "down",
            b"C": "right",
            b"D": "left",
            b"H": "home",
            b"F": "end",
            b"3~": "delete",
        }.get(bytes(sequence), "escape")
        return name, ""
    if first in {b"\r", b"\n"}:
        return "enter", ""
    if first == b"\t":
        return "tab", ""
    if first in {b"\x7f", b"\x08"}:
        return "backspace", ""
    if first == b"\x04":
        return "eof", ""
    if first == b"\x15":
        return "clear", ""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    result = decoder.decode(first)
    while not result:
        following = os.read(fd, 1)
        if not following:
            return "eof", ""
        result = decoder.decode(following)
    return "char", result


def _render(command: str, cursor: int, selected: int, previous_rows: int) -> int:
    width = max(20, shutil.get_terminal_size((80, 24)).columns)
    matches = suggestions(command)
    lines = [
        _fit(
            ("› " if index == selected else "  ")
            + match.name
            + "  "
            + match.description,
            width - 1,
        )
        for index, match in enumerate(matches)
    ]
    if matches:
        lines.append(_fit("  Tab เติมคำสั่ง · ↑↓ เลือก · Enter ยืนยัน", width - 1))
    rows = max(previous_rows, len(lines))
    sys.stderr.write("\r\x1b[2K> " + command)
    for index in range(rows):
        sys.stderr.write("\n\x1b[2K")
        if index < len(lines):
            sys.stderr.write(lines[index])
    if rows:
        sys.stderr.write(f"\x1b[{rows}A")
    sys.stderr.write("\r")
    position = 2 + _cell_width(command[:cursor])
    if position:
        sys.stderr.write(f"\x1b[{position}C")
    sys.stderr.flush()
    return len(lines)


def _slash_input(fd: int) -> str:
    command, cursor, selected, rows = "/", 1, -1, 0
    try:
        rows = _render(command, cursor, selected, rows)
        while True:
            key, value = _read_key(fd)
            matches = suggestions(command)
            if key == "enter":
                if 0 <= selected < len(matches):
                    command = matches[selected].name
                return command
            if key == "eof":
                if command == "/":
                    raise EOFError
                if cursor < len(command):
                    command = command[:cursor] + command[cursor + 1 :]
            elif key == "escape":
                return ""
            elif key == "tab" and matches:
                command = matches[selected if selected >= 0 else 0].name
                cursor = len(command)
                selected = -1
            elif key == "up" and matches:
                selected = (selected - 1) % len(matches)
            elif key == "down" and matches:
                selected = (selected + 1) % len(matches)
            elif key == "left":
                cursor = max(0, cursor - 1)
            elif key == "right":
                cursor = min(len(command), cursor + 1)
            elif key == "home":
                cursor = 0
            elif key == "end":
                cursor = len(command)
            elif key == "clear":
                command, cursor, selected = "/", 1, -1
            elif key == "backspace" and cursor > 0:
                command = command[: cursor - 1] + command[cursor:]
                cursor -= 1
                selected = -1
            elif key == "delete" and cursor < len(command):
                command = command[:cursor] + command[cursor + 1 :]
                selected = -1
            elif key == "char" and value.isprintable():
                next_command = command[:cursor] + value + command[cursor:]
                width = max(20, shutil.get_terminal_size((80, 24)).columns)
                if len(next_command) <= 80 and _cell_width(next_command) <= width - 3:
                    command = next_command
                    cursor += len(value)
                    selected = -1
            rows = _render(command, cursor, selected, rows)
    finally:
        sys.stderr.write("\r\x1b[2K> " + command + "\x1b[J\n")
        sys.stderr.flush()


def read_interactive_task() -> str:
    """Show live slash suggestions on a TTY; preserve readline for tasks."""
    if not (sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()):
        print("\n> ", end="", file=sys.stderr, flush=True)
        return input().strip()
    get_backend().require_terminal()
    import termios
    import tty
    try:
        import readline
    except ImportError:
        print("\n> ", end="", file=sys.stderr, flush=True)
        return input().strip()
    fd = sys.stdin.fileno()
    old_mode = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        print("\n> ", end="", file=sys.stderr, flush=True)
        while True:
            key, first = _read_key(fd)
            if key == "char" and first.isprintable():
                break
            if key == "enter":
                sys.stderr.write("\n")
                return ""
            if key == "eof":
                raise EOFError
        if first == "/":
            return _slash_input(fd).strip()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_mode)
    readline.set_startup_hook(lambda: readline.insert_text(first))
    try:
        return input().strip()
    finally:
        readline.set_startup_hook(None)
