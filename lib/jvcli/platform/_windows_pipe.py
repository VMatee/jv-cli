"""Bounded workers for synchronous Windows stdio pipes.

Anonymous CreatePipe handles cannot be made overlapped. Each worker owns only
one pending ReadFile/WriteFile and no application state. Cancellation is repeated
until the worker exits, covering the race before a synchronous call begins.
"""
from __future__ import annotations

import ctypes as C
import msvcrt
import queue
import threading
import time

from . import _windows_fs as fs

W, D, P = fs.W, fs.D, fs.P
get_type = fs._api(fs.K, "GetFileType", D, W.HANDLE)
read_file = fs._api(fs.K, "ReadFile", W.BOOL, W.HANDLE, P, D, C.POINTER(D), P)
write_file = fs._api(fs.K, "WriteFile", W.BOOL, W.HANDLE, P, D, C.POINTER(D), P)
open_thread = fs._api(fs.K, "OpenThread", W.HANDLE, D, W.BOOL, D)
cancel_sync = fs._api(fs.K, "CancelSynchronousIo", W.BOOL, W.HANDLE)
query_file = fs._api(fs.N, "NtQueryInformationFile", W.LONG, W.HANDLE,
                    C.POINTER(fs.IoStatus), P, D, C.c_int)


class PipeWorker:
    def __init__(self, fd, *, writing=False):
        self.handle = msvcrt.get_osfhandle(fd)
        if get_type(self.handle) != 3:  # FILE_TYPE_PIPE: consoles/files are not stdio IPC.
            raise OSError("Windows bridge requires redirected pipe handles")
        status, mode = fs.IoStatus(), D()
        if query_file(self.handle, C.byref(status), C.byref(mode), C.sizeof(mode), 16) < 0 or not mode.value & 0x30:
            raise OSError("Windows bridge requires synchronous pipe handles")
        if self._pipe_info()[0] != 0:
            raise OSError("Windows bridge requires byte-stream pipes")
        self.writing = writing
        self.requests = queue.Queue(maxsize=1)
        self.results = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.pending = False
        self.thread_handle = None
        self.start_error = None
        self.thread = threading.Thread(target=self._run, name="bridge-pipe-io", daemon=True)
        self.thread.start()
        self.ready.wait()
        if self.start_error:
            self.thread.join()
            raise self.start_error

    def _run(self):
        try:
            # Keep the thread handle until its owner has stopped issuing cancel
            # calls. A recycled thread ID must never redirect cancellation.
            self.thread_handle = fs._check(open_thread(1, False, threading.get_native_id()))
        except OSError as exc:
            self.start_error = exc
        finally:
            self.ready.set()
        if self.start_error:
            return
        while not self.stopping.is_set():
            try:
                data = self.requests.get(timeout=.05)
            except queue.Empty:
                continue
            if self.stopping.is_set():
                return
            buffer = C.create_string_buffer(data) if self.writing else C.create_string_buffer(4096)
            count = D()
            function = write_file if self.writing else read_file
            ok = function(self.handle, buffer, len(data) if self.writing else 4096, C.byref(count), None)
            error = C.get_last_error() if not ok else 0
            if self.stopping.is_set():
                return
            if error and not (not self.writing and error in (109, 232, 233)):
                result = OSError(error, "Windows bridge pipe operation failed")
            else:
                result = count.value if self.writing else buffer.raw[:count.value]
            self.results.put_nowait(result)  # Exactly one outstanding operation.

    def _start(self, data):
        if self.stopping.is_set():
            raise BrokenPipeError()
        if not self.pending:
            self.requests.put_nowait(data)
            self.pending = True

    def _pipe_info(self):
        status, info = fs.IoStatus(), (D * 10)()
        if query_file(self.handle, C.byref(status), info, C.sizeof(info), 24) < 0:
            raise BrokenPipeError()
        return info

    def check_connected(self):
        # Only queried by the emitter between writes, never concurrently with
        # synchronous I/O on this handle. Detect idle peer death without output.
        if self._pipe_info()[8] != 3:
            raise BrokenPipeError()

    def _result(self, timeout):
        try:
            result = self.results.get(timeout=timeout)
        except queue.Empty:
            return None
        self.pending = False
        if isinstance(result, OSError):
            raise result
        return result

    def read(self):
        self._start(None)
        return self._result(.1)

    def write(self, raw, deadline, failed):
        self._start(bytes(raw))
        while not failed.is_set() and time.monotonic() < deadline:
            result = self._result(min(.05, max(0, deadline - time.monotonic())))
            if result is not None:
                return result
        self.close()
        raise BrokenPipeError()

    def close(self):
        self.stopping.set()
        until = time.monotonic() + 1
        while self.thread.is_alive() and time.monotonic() < until:
            if self.thread_handle:
                if not cancel_sync(self.thread_handle) and C.get_last_error() != 1168:
                    raise OSError("Windows bridge pipe cancellation failed")
            self.thread.join(.01)
        if self.thread.is_alive():
            # Do not close/reuse handles while a syscall might still own them.
            # The bridge must exit; no healthy continuation is permitted.
            raise OSError("Windows bridge pipe worker did not stop")
        if self.thread_handle:
            fs._close(self.thread_handle)
            self.thread_handle = None
