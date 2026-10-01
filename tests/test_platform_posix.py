"""Real POSIX regression checks for the extracted OS boundary."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import cli
from jvcli.platform import get_backend, state_directory
from jvcli.safety import atomic_write, private_dir, read_private_json


@unittest.skipUnless(os.name == "posix", "POSIX OS regression; excluded from Windows preflight")
class PosixPlatformRegression(unittest.TestCase):
    def test_linux_state_selection_is_unchanged(self):
        self.assertEqual(state_directory(ROOT, {}), ROOT / ".state")
        self.assertEqual(state_directory(ROOT, {"JVCLI_HOME": "relative-state"}),
                         Path("relative-state").absolute())

    def test_private_permissions_and_shared_json_reader(self):
        with tempfile.TemporaryDirectory() as td:
            directory = private_dir(Path(td) / "private")
            file = directory / "state.json"
            atomic_write(file, '{"synthetic":true}\n')
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertEqual(read_private_json(file), {"synthetic": True})

    def test_real_shared_and_exclusive_lock_contention_and_release(self):
        backend = get_backend()
        code = (
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "from jvcli.platform import get_backend; p=get_backend(); "
            "h=p.open_lock(sys.argv[2]);\n"
            "try:\n p.lock_file(h,shared=sys.argv[3]=='shared'); print('acquired')\n"
            "except BlockingIOError:\n print('blocked')\n"
            "finally:\n p.close_lock(h)\n"
        )
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "lock"
            with self.assertRaises(FileNotFoundError):
                backend.open_lock(file, create=False)
            self.assertFalse(file.exists())
            owner = backend.open_lock(file)
            try:
                backend.lock_file(owner, shared=True)
                for mode, expected in (("shared", "acquired"), ("exclusive", "blocked")):
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", code, str(ROOT / "lib"), str(file), mode],
                        env=cli._minimal_env(), capture_output=True, text=True, timeout=5, check=True,
                    )
                    self.assertEqual(result.stdout.strip(), expected)
            finally:
                backend.close_lock(owner)
            result = subprocess.run(
                [sys.executable, "-B", "-c", code, str(ROOT / "lib"), str(file), "exclusive"],
                env=cli._minimal_env(), capture_output=True, text=True, timeout=5, check=True,
            )
            self.assertEqual(result.stdout.strip(), "acquired")

    def test_owned_argv_spawn_preserves_unicode_stdin_and_process_group(self):
        backend = get_backend()
        code = (
            "import json,os,sys; "
            "print(json.dumps({'argv':sys.argv[1:],'text':sys.stdin.read(),"
            "'own_group':os.getpgrp()==os.getpid()},ensure_ascii=False))"
        )
        marker = 'ทดสอบ & $(command) `command` "quoted"'
        process = backend.spawn_engine([sys.executable, "-B", "-c", code], cli._minimal_env())
        try:
            output, errors = process.communicate(marker, timeout=5)
            self.assertEqual(process.returncode, 0, errors)
            self.assertEqual(json.loads(output), {"argv": [], "text": marker, "own_group": True})
        finally:
            if process.poll() is None:
                backend.stop_process(process)


if __name__ == "__main__":
    unittest.main()
