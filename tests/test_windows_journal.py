"""Native durable journal tests; process crashes are not power-loss simulation."""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli.structured import DurableResponseState
from jvcli.safety import JvError, read_private_json
if os.name == 'nt':
    from jvcli.platform import _windows_fs as fs


@unittest.skipUnless(os.name == 'nt', 'Requires native NTFS write-through and rename')
class WindowsJournal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='staging-journal-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = DurableResponseState(self.root / 'journal')

    def write(self, text='ภาษาไทย 🐈'):
        self.state.value['synthetic'] = text
        self.state._write()

    def read(self):
        return read_private_json(self.state.path)

    def test_new_replace_unicode_and_reopen(self):
        self.write()
        self.assertEqual(DurableResponseState(self.state.directory).value['synthetic'], 'ภาษาไทย 🐈')
        self.write('second')
        self.assertEqual(self.read()['synthetic'], 'second')

    def test_actual_write_through_mode_and_two_flushes(self):
        query = fs._api(fs.N, 'NtQueryInformationFile', fs.W.LONG, fs.W.HANDLE,
                        C.POINTER(fs.IoStatus), fs.P, fs.D, C.c_int)
        original = fs.rename_file
        def rename(handle, parent, name):
            status, mode = fs.IoStatus(), fs.D()
            fs.ntcheck(query(handle, C.byref(status), C.byref(mode), C.sizeof(mode), 16))
            self.assertTrue(mode.value & 2)
            return original(handle, parent, name)
        with patch.object(fs, 'rename_file', side_effect=rename), patch.object(fs.os, 'fsync', wraps=os.fsync) as flush:
            self.write()
            self.assertEqual(flush.call_count, 2)

    def test_pre_rename_flush_failure_preserves_previous(self):
        self.write('old')
        with patch.object(fs.os, 'fsync', side_effect=OSError('synthetic flush failure')):
            with self.assertRaises(JvError):
                self.write('new')
        self.assertTrue(self.state.write_failed)
        self.assertEqual(self.read()['synthetic'], 'old')
        self.assertFalse(list(self.state.directory.glob('.jv-write-*')))

    def test_rename_failure_preserves_previous(self):
        self.write('old')
        with patch.object(fs, 'rename_file', side_effect=OSError('synthetic rename failure')):
            with self.assertRaises(JvError):
                self.write('new')
        self.assertEqual(self.read()['synthetic'], 'old')
        self.assertFalse(list(self.state.directory.glob('.jv-write-*')))

    def test_post_rename_flush_failure_is_not_success(self):
        self.write('old')
        original = os.fsync
        calls = []
        def flush(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('synthetic final flush failure')
            return original(fd)
        with patch.object(fs.os, 'fsync', side_effect=flush):
            with self.assertRaises(JvError):
                self.write('new')
        self.assertTrue(self.state.write_failed)
        self.assertEqual(self.read()['synthetic'], 'new')
        self.assertFalse(list(self.state.directory.glob('.jv-write-*')))

    def test_partial_temp_is_never_current(self):
        self.write('old')
        (self.state.directory / '.jv-write-incomplete').write_bytes(b'{"partial":')
        self.assertEqual(DurableResponseState(self.state.directory).value['synthetic'], 'old')

    def test_rapid_replacements_observed_by_reader(self):
        self.write('old')
        stop, errors, observed = threading.Event(), [], []
        def read():
            while not stop.is_set():
                try:
                    observed.append(self.read()['synthetic'])
                except OSError:
                    pass  # Sharing contention must fail, never return partial JSON.
                except Exception as exc:
                    errors.append(type(exc).__name__)
        thread = threading.Thread(target=read)
        thread.start()
        try:
            for i in range(30):
                try:
                    self.write(str(i))
                except JvError:
                    pass  # A live no-delete-share reader can reject replacement.
        finally:
            stop.set(); thread.join(3)
        self.assertFalse(errors)
        self.assertTrue(observed)
        self.write('final')
        self.assertEqual(self.read()['synthetic'], 'final')

    def test_process_exit_then_reopen(self):
        code = "import sys; sys.path.insert(0,sys.argv[1]); from pathlib import Path; from jvcli.structured import DurableResponseState; s=DurableResponseState(Path(sys.argv[2])); s.prepare('synthetic',{'text':'Unicode \\u0e44\\u0e17\\u0e22'}); "
        result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'lib'), str(self.state.directory)], capture_output=True, timeout=10, shell=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        reopened = DurableResponseState(self.state.directory)
        self.assertEqual(reopened.rounds[0]['phase'], 'prepared')
        self.assertEqual(reopened.rounds[0]['body']['text'], 'Unicode ไทย')

    def test_partial_write_failure_cleans_temp_and_preserves_old(self):
        self.write('old')
        original = os.write
        calls = []
        def write(fd, data):
            calls.append(fd)
            if len(calls) > 1:
                raise OSError('synthetic partial write')
            return original(fd, data[:5])
        with patch.object(fs.os, 'write', side_effect=write):
            with self.assertRaises(JvError):
                self.write('new')
        self.assertEqual(self.read()['synthetic'], 'old')
        self.assertFalse(list(self.state.directory.glob('.jv-write-*')))

    def test_crash_before_rename_preserves_active_record(self):
        self.write('old')
        code = "import sys; sys.path.insert(0,sys.argv[1]); from pathlib import Path; from jvcli.structured import DurableResponseState; from jvcli.platform import _windows_fs as f; s=DurableResponseState(Path(sys.argv[2])); f.rename_file=lambda *a: (print('ready',flush=True),sys.stdin.buffer.read(1)); s.value['synthetic']='new'; s._write()"
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT / 'lib'), str(self.state.directory)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        try:
            self.assertEqual(child.stdout.readline().strip(), b'ready')
            child.kill()
            child.communicate(timeout=5)
            self.assertEqual(DurableResponseState(self.state.directory).value['synthetic'], 'old')
            self.assertTrue(list(self.state.directory.glob('.jv-write-*')))
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_sequential_replacements_reopen_every_record(self):
        for index in range(30):
            self.write(str(index))
            self.assertEqual(DurableResponseState(self.state.directory).value['synthetic'], str(index))
