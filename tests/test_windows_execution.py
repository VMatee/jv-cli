"""Native argv, environment, package-discovery and owned-job tests."""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from windows_test_support import trusted_fixture_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import cli
from jvcli.platform import windows as w
from jvcli.safety import JvError
if os.name == "nt":
    from jvcli.platform import _windows_engine as eng, _windows_process as proc, _windows_fs as fs


@unittest.skipUnless(os.name == "nt", "Requires native Windows process creation and Job Objects")
class WindowsExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = tempfile.TemporaryDirectory(prefix="staging-python-", dir=ROOT)
        cls.addClassCleanup(cls.runtime.cleanup)
        target = Path(cls.runtime.name)
        trusted_fixture_directory(target)
        # Do not weaken executable ACL validation when the development Python
        # installation permits writes by another principal. Stage only binaries;
        # use its known standard library explicitly, never user site/config.
        for name in ("python.exe", f"python{sys.version_info.major}{sys.version_info.minor}.dll", "python3.dll"):
            source = Path(sys.executable).parent / name
            if source.exists():
                shutil.copyfile(source, target / name)
        cls.python = str(target / "python.exe")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="staging-execution-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        trusted_fixture_directory(self.root)
        self.env = w.isolated_env(self.root / "state")
        self.env["PYTHONHOME"] = sys.base_prefix

    def spawn(self, body):
        return w.spawn_engine([self.python, "-B", "-s", "-c", body], self.env)

    def close(self, process):
        w.stop_process(process)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()

    def tree(self, role="parent"):
        marker = self.root / "pids.json"
        process = w.spawn_engine([self.python, "-B", str(ROOT / "tests/fixtures/windows_process_tree.py"),
                                  role, str(marker)], self.env)
        self.addCleanup(self.close, process)
        return process, self.pids(marker)

    def pids(self, marker):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            try:
                return json.loads(marker.read_text())
            except (FileNotFoundError, ValueError):
                time.sleep(.02)
        self.fail("Synthetic process tree did not report readiness")

    def process_handles(self, pids):
        open_process = fs._api(fs.K, "OpenProcess", fs.W.HANDLE, fs.D, fs.W.BOOL, fs.D)
        handles = []
        for pid in pids:
            handle = fs._check(open_process(0x100000, False, pid))
            handles.append(handle)
            self.addCleanup(fs._close, handle)
        return handles

    def test_prompt_unicode_stays_on_stdin(self):
        process = self.spawn("import json,sys; print(json.dumps({'argv':sys.argv[1:],'input':sys.stdin.read()},ensure_ascii=False))")
        prompt = 'ภาษาไทย é 😀 & $(not-a-command) `literal` "quoted"\nsecond line'
        out, err = process.communicate(prompt, timeout=10)
        self.assertEqual(process.returncode, 0, err)
        self.assertEqual(json.loads(out), {"argv": [], "input": prompt})
        self.assertNotIn(prompt, process.args)

    def test_environment_excludes_parent_secrets_and_config(self):
        names = ("JV_API_PASSWORD", "OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "JVCLI_ADAPTER_KEY")
        with patch.dict(os.environ, {**{k: "synthetic-secret" for k in names},
                                    "USERPROFILE": "C:\\synthetic-user", "PATH": "C:\\untrusted"}):
            env = w.isolated_env(self.root / "isolated")
        self.assertFalse(set(names) & env.keys())
        self.assertNotIn("untrusted", env["PATH"])
        self.assertNotIn("synthetic-user", " ".join(env.values()))
        env["PYTHONHOME"] = sys.base_prefix
        body = "import os,json; print(json.dumps({'leaked':any(k in os.environ for k in " + repr(names) + "),'home':os.environ['USERPROFILE']}))"
        process = w.spawn_engine([self.python, "-B", "-c", body], env)
        out, _ = process.communicate(timeout=10)
        result = json.loads(out)
        self.assertFalse(result["leaked"])
        self.assertTrue(Path(result["home"]).is_relative_to(self.root))

    def test_tool_environment_excludes_explicit_engine_adapter_key(self):
        engine_env = w.isolated_env(self.root / "session", adapter_key="synthetic-adapter")
        policy = w.tool_environment(self.root / "session")
        self.assertEqual(engine_env["JVCLI_ADAPTER_KEY"], "synthetic-adapter")
        self.assertEqual(policy["inherit"], "none")
        self.assertNotIn("JVCLI_ADAPTER_KEY", policy["set"])
        self.assertNotEqual(engine_env["CODEX_HOME"], policy["set"]["CODEX_HOME"])
        cli._write_engine_config(self.root / "session", 12345)
        config = (self.root / "session/engine/config.toml").read_text()
        self.assertNotIn("synthetic-adapter", config)
        self.assertIn('"inherit" = "none"', config)

    def test_job_owns_process_before_first_instruction(self):
        body = "import ctypes as c; from ctypes import wintypes as w; k=c.WinDLL('kernel32'); k.GetCurrentProcess.restype=w.HANDLE; k.IsProcessInJob.argtypes=[w.HANDLE,w.HANDLE,c.POINTER(w.BOOL)]; b=w.BOOL(); assert k.IsProcessInJob(k.GetCurrentProcess(),None,c.byref(b)); print(bool(b.value))"
        out, _ = self.spawn(body).communicate(timeout=10)
        self.assertEqual(out.strip(), "True")

    def test_child_grandchild_cleanup_and_unrelated_survival(self):
        sentinel = self.spawn("import time;time.sleep(60)")
        self.addCleanup(self.close, sentinel)
        process, pids = self.tree()
        handles = self.process_handles(pids)
        w.stop_process(process)
        for handle in handles:
            self.assertEqual(proc.wait_handle(handle, 5000), 0)
        self.assertIsNone(sentinel.poll())

    def test_parent_exit_kills_orphaned_descendants(self):
        process, pids = self.tree("exit-parent")
        self.assertEqual(process.wait(10), 0)
        # OpenProcess may already fail after reaping, so query only existing PIDs.
        open_process = fs._api(fs.K, "OpenProcess", fs.W.HANDLE, fs.D, fs.W.BOOL, fs.D)
        for pid in pids[1:]:
            handle = open_process(0x100000, False, pid)
            if handle:
                try:
                    self.assertEqual(proc.wait_handle(handle, 5000), 0)
                finally:
                    fs._close(handle)

    def test_owner_process_death_kills_whole_job(self):
        marker = self.root / "pids.json"
        body = ("import sys;sys.path.insert(0,sys.argv[1]);from jvcli.platform import windows as w;"
                "p=w.spawn_engine(sys.argv[2:],dict(__import__('os').environ));sys.stdin.read()")
        owner = subprocess.Popen([self.python, "-B", "-c", body, str(ROOT / "lib"), self.python,
                                  "-B", str(ROOT / "tests/fixtures/windows_process_tree.py"),
                                  "parent", str(marker)], env=self.env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        try:
            handles = self.process_handles(self.pids(marker))
            owner.kill()
            owner.wait(10)
            for handle in handles:
                self.assertEqual(proc.wait_handle(handle, 5000), 0)
        finally:
            if owner.poll() is None:
                owner.kill()
            owner.communicate(timeout=10)

    def test_breakaway_is_denied(self):
        body = ("import subprocess,sys\ntry:\n subprocess.Popen([sys.executable,'-c','pass'],creationflags=0x1000000)\n"
                "except PermissionError:\n print('denied')\nelse:\n raise RuntimeError('escaped job')")
        out, err = self.spawn(body).communicate(timeout=10)
        self.assertEqual(out.strip(), "denied", err)

    def test_wait_timeout_and_diagnostic_cleanup(self):
        process = self.spawn("import time;time.sleep(60)")
        with self.assertRaises(subprocess.TimeoutExpired):
            process.communicate(timeout=.1)
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdout.closed)

    def test_diagnostic_output_is_bounded(self):
        process = self.spawn("import sys;sys.stdout.write('x'*300000);sys.stdout.flush()")
        with self.assertRaisesRegex(JvError, "output exceeded"):
            process.communicate(timeout=10)
        self.assertIsNotNone(process.poll())

    def test_unknown_process_and_shell_shim_rejected(self):
        with self.assertRaises(JvError):
            w.stop_process(object())
        with self.assertRaises(JvError):
            w.spawn_engine([str(self.root / "codex.cmd")], self.env)
        with self.assertRaises(JvError):
            w.spawn_engine(["codex.exe"], self.env)

    def test_failed_creation_does_not_leak_handles(self):
        get_count = fs._api(fs.K, "GetProcessHandleCount", fs.W.BOOL, fs.W.HANDLE, C.POINTER(fs.D))
        def count():
            n = fs.D()
            fs._check(get_count(fs._process(), C.byref(n)))
            return n.value
        before = count()
        for _ in range(10):
            with self.assertRaises(FileNotFoundError):
                w.spawn_engine([str(self.root / "missing.exe")], self.env)
        self.assertLessEqual(count(), before + 1)

    def test_native_pe_and_shell_detection(self):
        self.assertEqual(eng.verify_executable(self.python), Path(self.python))
        invalid = self.root / "wrong.exe"
        invalid.write_bytes(b"not native")
        with self.assertRaises(JvError):
            eng.verify_executable(invalid)
        with self.assertRaises(JvError):
            eng.verify_executable(self.root / "codex.cmd")

    def test_discovery_missing_runtime(self):
        self.assertIsNone(w.find_engine(self.root / "missing"))

    def test_package_layout_pin_and_architecture(self):
        root = self.root / "runtime/node_modules/@openai/codex-win32-x64/vendor" / eng.TARGET
        header = bytearray(128)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 64)
        header[64:68] = b"PE\0\0"
        struct.pack_into("<H", header, 68, 0x8664)
        struct.pack_into("<H", header, 86, 2)
        struct.pack_into("<H", header, 88, 0x20B)
        for name in ("bin/codex.exe", "codex-resources/codex-command-runner.exe",
                     "codex-resources/codex-windows-sandbox-setup.exe", "codex-path/rg.exe"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(header)
        metadata = {"layoutVersion": 1, "version": cli.ENGINE_VERSION, "target": eng.TARGET,
                    "variant": "codex", "entrypoint": "bin/codex.exe",
                    "resourcesDir": "codex-resources", "pathDir": "codex-path"}
        manifest = root / "codex-package.json"
        manifest.write_text(json.dumps(metadata))
        self.assertEqual(w.find_engine(self.root / "runtime"), str(root / "bin/codex.exe"))
        metadata["version"] = "0.0.0"
        manifest.write_text(json.dumps(metadata))
        with self.assertRaises(JvError):
            w.find_engine(self.root / "runtime")
        struct.pack_into("<H", header, 68, 0xAA64)
        (root / "bin/codex.exe").write_bytes(header)
        with self.assertRaises(JvError):
            eng.verify_executable(root / "bin/codex.exe")

    def test_sessions_remain_blocked_before_authentication(self):
        with patch.object(cli, "_resolve_account", side_effect=AssertionError("auth reached")):
            with self.assertRaisesRegex(JvError, "session sandbox"):
                with cli._session_runtime():
                    self.fail("Unaccepted native session enabled")

    def test_version_mismatch_is_rejected_using_real_process(self):
        with patch.object(cli, "_diagnostic_env", return_value=self.env):
            with self.assertRaisesRegex(JvError, "pinned version"):
                cli._version_of_engine(self.python)

    def test_shared_runner_timeout_and_prompt_delivery(self):
        body = "import sys,json;assert sys.stdin.read().strip()=='synthetic';print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'ok'}}));print(json.dumps({'type':'turn.completed'}))"
        with patch.object(cli, "_engine_command", return_value=[self.python, "-B", "-c", body]), \
                patch.object(cli, "_engine_env", return_value=self.env):
            self.assertEqual(cli._run_engine(self.python, "synthetic", None, render_terminal=False), (0, None))
        with patch.object(cli, "_engine_command", return_value=[self.python, "-B", "-c", "import time;time.sleep(60)"]), \
                patch.object(cli, "_engine_env", return_value=self.env):
            self.assertEqual(cli._run_engine(self.python, "x" * 90000, None, turn_timeout=.1, render_terminal=False)[0], 124)


if __name__ == "__main__":
    unittest.main()
