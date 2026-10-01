"""Portable handoff contracts; these do not validate Windows OS security."""
import contextlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import bridge, cli
from jvcli.platform import get_backend, state_directory
from jvcli.platform.common import (
    PlatformUnavailableError, native_executable_name,
)
from jvcli.safety import JvError, strict_json


class PlatformContracts(unittest.TestCase):
    def test_actual_platform_dispatch(self):
        self.assertEqual(get_backend().__name__, "jvcli.platform." + (
            "windows" if os.name == "nt" else "posix"))

    def test_windows_backend_is_importable_without_posix_modules(self):
        self.assertEqual(get_backend("nt").__name__, "jvcli.platform.windows")

    def test_unknown_platform_is_actionable(self):
        with self.assertRaisesRegex(JvError, "Unsupported JV CLI platform"):
            get_backend("unknown")

    def test_windows_normal_terminal_state_location(self):
        path = state_directory(ROOT, {"LOCALAPPDATA": r"C:\Users\Tester\AppData\Local"},
                               platform_name="nt")
        self.assertEqual(path, PureWindowsPath(r"C:\Users\Tester\AppData\Local\JV\jv-cli"))

    def test_desktop_state_override_takes_precedence(self):
        value = r"D:\Desktop private\สถานะ JV"
        path = state_directory(ROOT, {"JVCLI_HOME": value, "LOCALAPPDATA": r"C:\Local"},
                               platform_name="nt")
        self.assertEqual(path, PureWindowsPath(value))

    def test_windows_override_needs_no_linux_home(self):
        path = state_directory(ROOT, {"JVCLI_HOME": r"D:\Isolated\State"}, platform_name="nt")
        self.assertEqual(path, PureWindowsPath(r"D:\Isolated\State"))

    def test_windows_state_no_project_fallback(self):
        with self.assertRaisesRegex(JvError, "LOCALAPPDATA"):
            state_directory(ROOT, {}, platform_name="nt")

    def test_spaces_unicode_thai_and_longish_state_paths(self):
        for value in (r"C:\JV state\config", r"D:\ผู้ใช้\ทดสอบ\é\😀",
                      "C:/Users/Tester/JV state", "C:\\" + "long-segment\\" * 20 + "state"):
            with self.subTest(value=value):
                self.assertEqual(state_directory(ROOT, {"JVCLI_HOME": value}, platform_name="nt"),
                                 PureWindowsPath(value))

    def test_unc_is_only_lexically_accepted(self):
        value = r"\\server\share\JV state"
        path = state_directory(ROOT, {"JVCLI_HOME": value}, platform_name="nt")
        self.assertEqual(path, PureWindowsPath(value))
        with self.assertRaises(JvError):
            get_backend("nt").no_symlink_path(path)

    def test_relative_drive_and_device_state_paths_rejected(self):
        for value in (r"C:state", r"\state", "state", r"\\?\C:\state", r"\\.\pipe\state"):
            with self.subTest(value=value), self.assertRaises(JvError):
                state_directory(ROOT, {"JVCLI_HOME": value}, platform_name="nt")

    def test_reserved_and_ambiguous_state_components_rejected(self):
        for value in (r"C:\JV\CON", r"C:\JV\nul.txt", r"C:\JV\COM1.json",
                      r"C:\JV\LPT¹", r"C:\JV\CON .txt", r"C:\JV\state:stream",
                      "C:\\JV\\trailing.", "C:\\JV\\trailing ", r"C:\JV\..\state",
                      "C:\\JV\\control\x00name", r"C:\JV\bad*name"):
            with self.subTest(value=value), self.assertRaises(JvError):
                state_directory(ROOT, {"JVCLI_HOME": value}, platform_name="nt")

    def test_path_case_is_preserved_without_claiming_native_identity(self):
        path = state_directory(ROOT, {"JVCLI_HOME": r"C:\JV\MiXeD"}, platform_name="nt")
        self.assertEqual(str(path), r"C:\JV\MiXeD")
        # Native identity/reparse checks belong to test_windows_native, not this lexical test.

    def test_native_executable_names(self):
        for name in ("jvcli", "codex", "node"):
            self.assertEqual(native_executable_name(name, platform_name="nt"), name + ".exe")
            self.assertEqual(native_executable_name(name, platform_name="posix"), name)
        self.assertEqual(native_executable_name("jvcli.EXE", platform_name="nt"), "jvcli.EXE")
        with self.assertRaises(JvError):
            native_executable_name("jvcli", platform_name="unknown")

    def test_unimplemented_windows_operations_fail_without_touching_files(self):
        windows = get_backend("nt")
        with contextlib.ExitStack() as stack:
            for name in ("open", "mkdir", "chmod", "replace", "kill"):
                stack.enter_context(patch.object(os, name, side_effect=AssertionError("OS mutation")))
            stack.enter_context(patch.object(cli.subprocess, "Popen", side_effect=AssertionError("spawn")))
            calls = (
                lambda: windows.find_engine(ROOT, "codex.cmd"),
                lambda: windows.spawn_engine(["codex.exe", "exec", "-"], {}),
                lambda: windows.stop_process(object()), lambda: windows.require_terminal(),
                lambda: windows.require_bridge_io(),
            )
            for operation in calls:
                with self.assertRaisesRegex(PlatformUnavailableError, "WINDOWS_NATIVE_HANDOFF"):
                    operation()
            with self.assertRaises(PlatformUnavailableError), windows.deadline(1, TimeoutError):
                self.fail("Windows deadline must not yield")

    def test_unimplemented_windows_bridge_never_announces_ready(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(cli, "get_backend", return_value=get_backend("nt")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["bridge", "--stdio"]), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("not implemented", err.getvalue())

    def test_shared_engine_argv_and_stdin_marker(self):
        engine = r"C:\Program Files\JV\codex.exe"
        command = cli._engine_command(engine, None, overrides=["-c", "model=\"jv-local\""])
        self.assertEqual(command, [engine, "-c", "model=\"jv-local\"", "exec", "--json",
                                  "--skip-git-repo-check", "--ignore-rules", "--color", "never", "-"])
        for shell in ("cmd.exe", "powershell", "pwsh", "-Command", "/c"):
            self.assertNotIn(shell, command)

    def test_shared_resume_and_image_argv_preserve_paths(self):
        image = PureWindowsPath(r"D:\งาน\image space.png")
        command = cli._engine_command("codex.exe", "thread_1", images=[image])
        self.assertEqual(command[:4], ["codex.exe", "exec", "resume", "thread_1"])
        self.assertEqual(command[-3:], ["--image", str(image), "-"])
        self.assertNotIn("--color", command)

    def test_bridge_prompt_unicode_and_shell_metacharacters_stay_data(self):
        prompt = 'ทดสอบ C:\\งาน\\file & $(command) `command` "quoted"\nnext line'
        request = strict_json(json.dumps({"type": "turn.start", "request_id": "r1", "text": prompt},
                                        ensure_ascii=False))
        self.assertEqual(bridge.validate(request), "turn.start")
        self.assertEqual(request["text"], prompt)
        self.assertNotIn(prompt, cli._engine_command("codex.exe", None))

    def test_protocol_one_and_error_schema_remain_shared(self):
        self.assertEqual(bridge.PROTOCOL, 1)
        for version in (2, True, "1"):
            with self.subTest(version=version), self.assertRaises(bridge.RequestError) as result:
                bridge.validate({"type": "bridge.shutdown", "request_id": "r", "protocol": version})
            self.assertEqual(result.exception.code, "unsupported_protocol")

    def test_permission_mapping_remains_shared(self):
        for fields in ({}, {"read_only": True}, {"allow_network": False}, {"allow_network": True}):
            self.assertEqual(bridge.validate({"type": "session.start", "request_id": "r", **fields}),
                             "session.start")
        for fields in ({"read_only": True, "allow_network": True}, {"read_only": 1},
                       {"allow_network": "false"}):
            with self.subTest(fields=fields), self.assertRaises(bridge.RequestError):
                bridge.validate({"type": "session.start", "request_id": "r", **fields})

    def test_shared_event_normalization_preserves_windows_file_paths(self):
        value = r"C:\งาน\space name.txt"
        normalized = bridge.normalize({"type": "item.completed", "item": {"type": "file_change",
                                     "changes": [{"path": value, "kind": "update"}]}})
        self.assertEqual(normalized, {"type": "files.changed", "changes": [{"path": value, "kind": "update"}]})


if __name__ == "__main__":
    unittest.main()
