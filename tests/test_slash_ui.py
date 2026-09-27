"""Local-only tests for interactive command discovery and Unicode input."""

import errno
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli.slash_ui import command_action, help_text, suggestions, unknown_command_message
from jvcli.protocol import BASE_AGENT_INSTRUCTIONS, build_jv_prompt
from jvcli.structured import STRUCTURED_AGENT_INSTRUCTIONS


class SlashCommandTests(unittest.TestCase):
    def test_commands_are_exact_and_english(self):
        self.assertEqual(command_action("/status"), "status")
        self.assertEqual(command_action("/permission"), "permissions")
        self.assertEqual(command_action("/permissions"), "permissions")
        self.assertEqual(command_action("/exit"), "exit")
        self.assertEqual(command_action("/quit"), "exit")
        self.assertEqual(command_action("/logout"), "logout")
        for value in ("/stat", "/สถานะ", "/status now", "สถานะ"):
            self.assertIsNone(command_action(value))

    def test_prefix_and_spelling_suggestions_do_not_execute(self):
        self.assertIn("/status", [item.name for item in suggestions("/sta")])
        self.assertEqual(suggestions("/sttaus")[0].name, "/status")
        self.assertIn("/status", unknown_command_message("/sttaus"))
        self.assertIsNone(command_action("/sttaus"))
        self.assertEqual(suggestions("hello"), ())
        self.assertEqual(suggestions("/status now"), ())

    def test_help_describes_english_commands_in_thai(self):
        help_message = help_text()
        self.assertIn("/permissions (or /permission)", help_message)
        self.assertIn("/logout", help_message)
        self.assertIn("ภาษาไทย", help_message)

    def test_thai_task_is_preserved_and_both_modes_request_matching_language(self):
        task = "ช่วยอธิบายไฟล์นี้เป็นภาษาไทย 🚲"
        prompt, _ = build_jv_prompt({"input": task, "tools": []})
        self.assertIn(task, prompt)
        self.assertIn("including Thai", BASE_AGENT_INSTRUCTIONS)
        self.assertIn("including Thai", STRUCTURED_AGENT_INSTRUCTIONS)


class TerminalInputTests(unittest.TestCase):
    def start_input(self):
        master, slave = pty.openpty()
        child = subprocess.Popen(
            [sys.executable, "-B", "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); "
             "from jvcli.slash_ui import read_interactive_task; "
             "print('RESULT:' + read_interactive_task())", str(ROOT / "lib")],
            stdin=slave, stdout=slave, stderr=slave,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        os.close(slave)
        return child, master

    def read_until(self, master, marker, timeout=3):
        data = bytearray()
        deadline = time.monotonic() + timeout
        while marker not in data and time.monotonic() < deadline:
            if not select.select([master], [], [], 0.1)[0]:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            data.extend(chunk)
        self.assertIn(marker, data, data.decode("utf-8", "replace"))
        return bytes(data)

    def test_live_menu_tab_completion(self):
        child, master = self.start_input()
        try:
            self.read_until(master, b"> ")
            os.write(master, b"/st")
            live = self.read_until(master, b"/status")
            self.assertIn("ดูสถานะ".encode(), live)
            os.write(master, b"\t\r")
            result = self.read_until(master, b"RESULT:/status")
            child.wait(timeout=3)
            self.assertEqual(child.returncode, 0, result)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)

    def test_thai_task_passes_through_unchanged(self):
        child, master = self.start_input()
        task = "ช่วยตรวจโค้ด Python ให้หน่อย 🚲"
        try:
            self.read_until(master, b"> ")
            os.write(master, (task + "\n").encode())
            result = self.read_until(master, ("RESULT:" + task).encode())
            child.wait(timeout=3)
            self.assertEqual(child.returncode, 0, result)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)

    def test_arrow_selection_keeps_command_local(self):
        child, master = self.start_input()
        try:
            self.read_until(master, b"> ")
            os.write(master, b"/\x1b[B\x1b[B\r")
            result = self.read_until(master, b"RESULT:/status")
            child.wait(timeout=3)
            self.assertEqual(child.returncode, 0, result)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
