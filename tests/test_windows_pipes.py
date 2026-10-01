"""Actual Windows anonymous-pipe transport tests; no public bridge readiness claim."""
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import bridge_io as bio


@unittest.skipUnless(os.name == "nt", "Requires native Windows pipe I/O cancellation")
class WindowsPipes(unittest.TestCase):
    def pipe(self):
        r, w = os.pipe()
        self.addCleanup(self.close_fd, r)
        self.addCleanup(self.close_fd, w)
        return r, w

    @staticmethod
    def close_fd(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def reader(self, fd):
        reader = bio.LineReader(fd)
        self.addCleanup(reader.close)
        return reader

    def until(self, reader):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            line = reader.next()
            if line is not None:
                return line
        self.fail("Native reader did not return a frame")

    def test_fragmented_thai_unicode_crlf_and_final_line(self):
        r, w = self.pipe()
        reader = self.reader(r)
        raw = '{"text":"ภาษาไทย 🐈"}\r\nlast'.encode()
        for byte in raw:
            os.write(w, bytes([byte]))
            if byte != 10:
                self.assertIsNone(reader.next())
            else:
                self.assertEqual(json.loads(self.until(reader)), {"text": "ภาษาไทย 🐈"})
        os.close(w)
        self.assertEqual(self.until(reader), b"last")
        self.assertIs(self.until(reader), bio.EOF)

    def test_invalid_utf8_is_not_replaced(self):
        r, w = self.pipe()
        reader = self.reader(r)
        os.write(w, b'"\xff"\n')
        with self.assertRaises(UnicodeError):
            self.until(reader).decode('utf-8')

    def test_blocked_read_is_pollable_and_cancelled(self):
        r, _ = self.pipe()
        reader = self.reader(r)
        start = time.monotonic()
        self.assertIsNone(reader.next())
        reader.close()
        self.assertFalse(reader.native.thread.is_alive())
        self.assertLess(time.monotonic() - start, 1.5)

    def test_read_ahead_is_bounded_and_oversize_recovers(self):
        r, w = self.pipe()
        reader = self.reader(r)
        raw = b'x' * (bio.MAX_LINE + 9000) + b'\nvalid\n'
        writer = threading.Thread(target=lambda: os.write(w, raw), daemon=True)
        writer.start()
        self.assertIs(self.until(reader), bio.OVERSIZE)
        self.assertLessEqual(len(reader.pending), bio.MAX_LINE + 4096)
        self.assertEqual(self.until(reader), b'valid')
        writer.join(2)
        self.assertFalse(writer.is_alive())

    def test_maximum_line_and_eof(self):
        r, w = self.pipe()
        reader = self.reader(r)
        raw = b'x' * bio.MAX_LINE
        writer = threading.Thread(target=lambda: os.write(w, raw), daemon=True)
        writer.start()
        # No newline: EOF must preserve the entire permitted line.
        closer = threading.Thread(target=lambda: (writer.join(), os.close(w)), daemon=True)
        closer.start()
        self.assertEqual(self.until(reader), raw)
        self.assertIs(self.until(reader), bio.EOF)
        closer.join(2)

    def test_utf8_output_is_binary_ndjson(self):
        r, w = self.pipe()
        emitter = bio.Emitter(w)
        self.addCleanup(emitter.close)
        emitter.emit({'text': 'ภาษาไทย 🐈', 'type': 'synthetic'})
        emitter.close()
        os.close(w)
        raw = os.read(r, 4096)
        self.assertEqual(raw, '{"text":"ภาษาไทย 🐈","type":"synthetic"}\n'.encode())
        self.assertFalse(emitter.failed.is_set())

    def test_large_frame_fragmentation(self):
        r, w = self.pipe()
        reader = self.reader(r)
        emitter = bio.Emitter(w)
        self.addCleanup(emitter.close)
        frame = {'text': 'ภาษาไทย' * 5000}
        emitter.emit(frame)
        self.assertEqual(json.loads(self.until(reader)), frame)
        emitter.close()
        self.assertFalse(emitter.failed.is_set())

    def test_blocked_writer_deadline_and_cleanup(self):
        r, w = self.pipe()
        with patch.object(bio, 'WRITE_TIMEOUT', .15):
            emitter = bio.Emitter(w)
            start = time.monotonic()
            emitter.emit({'text': 'x' * 100000})
            self.assertTrue(emitter.failed.wait(2))
            emitter.close()
        self.assertLess(time.monotonic() - start, 2)
        self.assertFalse(emitter.thread.is_alive())
        self.assertFalse(emitter.native.thread.is_alive())

    def test_queue_backpressure_is_bounded(self):
        _, w = self.pipe()
        emitter = bio.Emitter(w)
        self.addCleanup(emitter.close)
        with self.assertRaises(BrokenPipeError):
            for _ in range(bio.QUEUE_EVENTS + 2):
                emitter.emit({'text': 'x' * 100000})
        self.assertLessEqual(emitter.queue.qsize(), bio.QUEUE_EVENTS)
        emitter.close()
        self.assertFalse(emitter.native.thread.is_alive())

    def test_broken_pipe_and_oversized_output(self):
        r, w = self.pipe()
        emitter = bio.Emitter(w)
        self.addCleanup(emitter.close)
        os.close(r)
        emitter.emit({'type': 'synthetic'})
        self.assertTrue(emitter.failed.wait(2))
        emitter.close()
        r, w = self.pipe()
        emitter = bio.Emitter(w)
        self.addCleanup(emitter.close)
        with self.assertRaises(BrokenPipeError):
            emitter.emit({'text': 'x' * bio.MAX_EVENT})
        emitter.close()
        os.close(w)
        self.assertEqual(os.read(r, 4096), b'')

    def test_cancel_before_or_during_read_does_not_leak_workers(self):
        for _ in range(25):
            r, w = os.pipe()
            try:
                reader = bio.LineReader(r)
                reader.native._start(None)
                reader.close()
                self.assertFalse(reader.native.thread.is_alive())
                self.assertIsNone(reader.native.thread_handle)
            finally:
                os.close(r)
                os.close(w)

    def test_regular_files_are_explicitly_rejected(self):
        with tempfile.TemporaryFile(dir=ROOT) as stream:
            with self.assertRaises(OSError):
                bio.LineReader(stream.fileno())
            with self.assertRaises(OSError):
                bio.Emitter(stream.fileno())

    def fixture(self):
        from jvcli.platform.windows import minimal_env
        env = minimal_env()
        state = tempfile.TemporaryDirectory(prefix='staging-pipe-', dir=ROOT)
        self.addCleanup(state.cleanup)
        env['JVCLI_HOME'] = str(Path(state.name) / 'state')
        # Standard library location only; no arbitrary parent credentials/config.
        env['PYTHONHOME'] = sys.base_prefix
        process = subprocess.Popen(
            [sys.executable, '-B', '-s', str(ROOT / 'tests/fixtures/windows_pipe_bridge.py')],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        return process

    def test_shared_bridge_shutdown_and_eof_on_inherited_pipes(self):
        for raw in (b'', b'{"type":"bridge.shutdown","request_id":"stop"}',
                    b'{"type":"bridge.shutdown","request_id":"stop"}\r\nignored'):
            with self.subTest(raw=raw):
                process = self.fixture()
                stdout, stderr = process.communicate(raw, timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                frames = [json.loads(line) for line in stdout.splitlines()]
                self.assertEqual(frames[0]['type'], 'bridge.ready')
                self.assertEqual(frames[0]['protocol'], 1)
                self.assertEqual([f['type'] for f in frames[1:]], ['bridge.stopping'] if raw else [])
                self.assertEqual(stderr, b'')

    def test_shared_bridge_malformed_and_utf8_rejection(self):
        process = self.fixture()
        stdout, stderr = process.communicate(b'{bad}\n"\xff"\n[]\n', timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        frames = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual([f.get('code') for f in frames[1:]], ['invalid_request'] * 3)
        self.assertEqual(stderr, b'')

    def test_shared_bridge_broken_stdout_exits(self):
        process = self.fixture()
        self.assertEqual(json.loads(process.stdout.readline())['type'], 'bridge.ready')
        process.stdout.close()
        process.stdout = None
        process.wait(timeout=7)
        self.assertEqual(process.returncode, 2)

    def test_overlapped_pipe_is_rejected_before_io(self):
        import ctypes as C
        import msvcrt
        import uuid
        from jvcli.platform import _windows_fs as fs
        create = fs._api(fs.K, 'CreateNamedPipeW', fs.W.HANDLE, fs.W.LPCWSTR,
                         fs.D, fs.D, fs.D, fs.D, fs.D, fs.D, fs.P)
        handle = create('\\\\.\\pipe\\jv-test-' + uuid.uuid4().hex,
                        0x40000003, 0, 1, 4096, 4096, 0, None)
        self.assertNotEqual(handle, C.c_void_p(-1).value)
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY)
        try:
            with self.assertRaisesRegex(OSError, 'synchronous'):
                bio.LineReader(fd)
        finally:
            os.close(fd)


if __name__ == '__main__':
    unittest.main()
