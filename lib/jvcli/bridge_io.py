"""Shared bounded stdio framing with native pipe operations."""
from __future__ import annotations

import json
import os
import queue
import select
import threading
import time

MAX_LINE = 256 * 1024
MAX_EVENT = 128 * 1024
QUEUE_EVENTS = 64
WRITE_TIMEOUT = 5.0
EOF = object()
OVERSIZE = object()


class LineReader:
    def __init__(self, fd):
        self.fd = fd
        self.native = None
        if os.name == 'nt':
            from .platform._windows_pipe import PipeWorker
            self.native = PipeWorker(fd)
        self.pending = bytearray()
        self.discard = False
        self.eof = False

    def next(self):
        while True:
            end = self.pending.find(b'\n')
            if end >= 0:
                line = bytes(self.pending[:end])
                del self.pending[:end + 1]
                if self.discard:
                    self.discard = False
                    continue
                return line
            if self.eof:
                if self.pending and not self.discard:
                    line = bytes(self.pending)
                    self.pending.clear()
                    return line
                return EOF
            if self.native:
                chunk = self.native.read()
                if chunk is None:
                    return None
            else:
                if not select.select([self.fd], [], [], .1)[0]:
                    return None
                chunk = os.read(self.fd, 4096)
            if not chunk:
                self.eof = True
                continue
            self.pending.extend(chunk)
            if self.discard:
                end = self.pending.find(b'\n')
                if end < 0:
                    self.pending.clear()
                    return None
                del self.pending[:end + 1]
                self.discard = False
            # 4096-byte read overshoot is bounded; never buffer an unlimited line.
            end = self.pending.find(b'\n')
            length = len(self.pending) if end < 0 else end
            if length > MAX_LINE:
                if end < 0:
                    self.pending.clear()
                    self.discard = True
                else:
                    del self.pending[:end + 1]
                return OVERSIZE
            if end < 0:
                # Return control even when a peer continuously trickles bytes.
                # The owner must reap turns and notice failed stdout promptly.
                return None

    def close(self):
        if self.native:
            self.native.close()


class Emitter:
    """One writer; bounded queue and per-frame deadline. Failure stops the owner."""
    def __init__(self, fd):
        self.fd = fd
        self.queue = queue.Queue(maxsize=QUEUE_EVENTS)
        self.failed = threading.Event()
        self.closing = threading.Event()
        self.native = None
        if os.name == 'nt':
            from .platform._windows_pipe import PipeWorker
            self.native = PipeWorker(fd, writing=True)
        else:
            self.blocking = os.get_blocking(fd)
            os.set_blocking(fd, False)
        self.thread = threading.Thread(target=self._write, name='bridge-writer', daemon=True)
        self.thread.start()

    def emit(self, frame):
        if self.failed.is_set():
            raise BrokenPipeError()
        raw = (json.dumps(frame, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')) + '\n').encode('utf-8')
        if len(raw) > MAX_EVENT:
            self.failed.set()
            raise BrokenPipeError()
        try:
            self.queue.put(raw, timeout=.25)
        except queue.Full:
            self.failed.set()
            raise BrokenPipeError() from None

    def _write(self):
        poll = None
        if not self.native:
            poll = select.poll()
            poll.register(self.fd, select.POLLERR | select.POLLHUP | select.POLLNVAL)
        try:
            while not self.failed.is_set():
                if self.native:
                    self.native.check_connected()
                if poll and poll.poll(0):
                    raise BrokenPipeError()
                try:
                    raw = self.queue.get(timeout=.1)
                except queue.Empty:
                    if self.closing.is_set():
                        return
                    continue
                deadline = time.monotonic() + WRITE_TIMEOUT
                view = memoryview(raw)
                while view and not self.failed.is_set():
                    if time.monotonic() > deadline:
                        raise BrokenPipeError()
                    if self.native:
                        count = self.native.write(view, deadline, self.failed)
                    else:
                        if not select.select([], [self.fd], [], .1)[1]:
                            continue
                        try:
                            count = os.write(self.fd, view)
                        except BlockingIOError:
                            continue
                    if count <= 0:
                        raise BrokenPipeError()
                    view = view[count:]
        except (OSError, ValueError):
            self.failed.set()

    def close(self):
        self.closing.set()
        self.thread.join(WRITE_TIMEOUT + 1)
        if self.thread.is_alive():
            self.failed.set()
            self.thread.join(1)
        if self.native:
            if self.thread.is_alive():
                raise OSError('Windows bridge writer did not stop')
            self.native.close()
        else:
            os.set_blocking(self.fd, self.blocking)
