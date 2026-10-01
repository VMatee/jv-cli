"""Owned native process trees, assigned to a private job at CreateProcess time."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import io
import msvcrt
import os
from pathlib import Path
import subprocess
import threading

from . import _windows_fs as fs
from ..safety import JvError

K, D, P = fs.K, fs.D, fs.P
api, check = fs._api, fs._check


class BasicLimits(C.Structure):
    _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64),
                ("flags", D), ("min_working", C.c_size_t), ("max_working", C.c_size_t),
                ("active_limit", D), ("affinity", C.c_size_t), ("priority", D), ("scheduling", D)]


class IoCounters(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class ExtendedLimits(C.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                ("process_memory", C.c_size_t), ("job_memory", C.c_size_t),
                ("peak_process", C.c_size_t), ("peak_job", C.c_size_t)]


class StartupInfo(C.Structure):
    _fields_ = [("cb", D), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR), ("title", W.LPWSTR),
                ("x", D), ("y", D), ("x_size", D), ("y_size", D),
                ("x_chars", D), ("y_chars", D), ("fill", D), ("flags", D),
                ("show", W.WORD), ("reserved_size", W.WORD), ("reserved_ptr", P),
                ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]


class StartupInfoEx(C.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", P)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", D), ("tid", D)]


create_job = api(K, "CreateJobObjectW", W.HANDLE, P, W.LPCWSTR)
set_job = api(K, "SetInformationJobObject", W.BOOL, W.HANDLE, C.c_int, P, D)
terminate_job = api(K, "TerminateJobObject", W.BOOL, W.HANDLE, W.UINT)
initialize_attrs = api(K, "InitializeProcThreadAttributeList", W.BOOL, P, D, D, C.POINTER(C.c_size_t))
update_attr = api(K, "UpdateProcThreadAttribute", W.BOOL, P, D, C.c_size_t, P, C.c_size_t, P, P)
delete_attrs = api(K, "DeleteProcThreadAttributeList", None, P)
create_pipe = api(K, "CreatePipe", W.BOOL, C.POINTER(W.HANDLE), C.POINTER(W.HANDLE),
                  C.POINTER(fs.SecurityAttributes), D)
handle_flags = api(K, "SetHandleInformation", W.BOOL, W.HANDLE, D, D)
create_process = api(K, "CreateProcessW", W.BOOL, W.LPCWSTR, W.LPWSTR, P, P, W.BOOL,
                     D, P, W.LPCWSTR, C.POINTER(StartupInfoEx), C.POINTER(ProcessInfo))
wait_handle = api(K, "WaitForSingleObject", D, W.HANDLE, D)
exit_code = api(K, "GetExitCodeProcess", W.BOOL, W.HANDLE, C.POINTER(D))


class OwnedProcess:
    """Popen-compatible subset used by the shared runner; owns pipes and one job.

    A reaper terminates descendants even when the engine parent exits first.
    The non-inherited kill-on-close job also handles death of the JV CLI owner.
    No suspended child can escape between creation and assignment: JOB_LIST is
    an atomic process-creation attribute. Unsupported hosts fail before execution.
    """
    def __init__(self, command, env, *, inherited_handles=()):
        self.args = list(command)
        self.returncode = None
        self._done = threading.Event()
        self._mutex = threading.Lock()
        self._job = None
        self._error = None
        self.stdin = self.stdout = self.stderr = None
        if not command or not isinstance(command[0], str) or not Path(command[0]).is_absolute():
            raise JvError("Windows child execution requires an absolute native executable")
        if Path(command[0]).suffix.lower() != ".exe" or any(not isinstance(arg, str) or "\0" in arg for arg in command):
            raise JvError("Windows child execution requires native executable argv")
        if any(not isinstance(k, str) or not isinstance(v, str) or not k or "=" in k or "\0" in k + v
               for k, v in env.items()):
            raise JvError("Invalid Windows child environment")
        if len({k.upper() for k in env}) != len(env):
            raise JvError("Duplicate Windows child environment names")
        # Windows requires a command-line buffer, but list2cmdline only quotes
        # explicit argv; no shell interprets it. Prompt bytes are supplied on stdin.
        commandline = C.create_unicode_buffer(subprocess.list2cmdline(command))
        environment = C.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0\0")
        handles, streams = [], []
        attributes = None
        attributes_ready = False
        info = ProcessInfo()
        job = check(create_job(None, None))
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
            check(set_job(job, 9, C.byref(limits), C.sizeof(limits)))
            sa = fs.SecurityAttributes(C.sizeof(fs.SecurityAttributes), None, True)
            children, parents = [], []
            for index in range(3):
                read, write = W.HANDLE(), W.HANDLE()
                check(create_pipe(C.byref(read), C.byref(write), C.byref(sa), 0))
                handles.extend([read.value, write.value])
                parent, child = (write.value, read.value) if index == 0 else (read.value, write.value)
                check(handle_flags(parent, 1, 0))
                children.append(child)
                parents.append(parent)
            size = C.c_size_t()
            initialize_attrs(None, 2, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            check(initialize_attrs(attributes, 2, 0, C.byref(size)))
            attributes_ready = True
            inherited = (W.HANDLE * (3 + len(inherited_handles)))(*children, *inherited_handles)
            jobs = (W.HANDLE * 1)(job)
            check(update_attr(attributes, 0, 0x20002, inherited, C.sizeof(inherited), None, None))
            check(update_attr(attributes, 0, 0x2000D, jobs, C.sizeof(jobs), None, None))
            startup = StartupInfoEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = children
            startup.attributes = C.cast(attributes, P)
            executable = fs.native_path(command[0])
            with fs.ancestors(executable) as pinned:
                fs.inspect_public(pinned[-1], directory=True)
                binary, _ = fs.relative_open(pinned[-1], executable.name, access=0x80020000, share=1)
                try:
                    fs.inspect_public(binary)
                    check(create_process(str(executable), commandline, None, None, True,
                                         0x80400 | 0x08000000, environment, None,
                                         C.byref(startup), C.byref(info)))
                finally:
                    fs._close(binary)
            fs._close(info.thread)
            info.thread = None
            for child in children:
                fs._close(child)
                handles.remove(child)
            for index, parent in enumerate(parents):
                fd = msvcrt.open_osfhandle(parent, (os.O_WRONLY if index == 0 else os.O_RDONLY) | os.O_BINARY)
                handles.remove(parent)
                stream = os.fdopen(fd, "wb" if index == 0 else "rb", buffering=0)
                streams.append(io.TextIOWrapper(stream, encoding="utf-8", errors="replace", newline="\n", write_through=True))
            self.stdin, self.stdout, self.stderr = streams
            self.pid = info.pid
            self._job = job
            self._process = info.process
            self._reaper = threading.Thread(target=self._reap, name="jv-windows-job", daemon=True)
            self._reaper.start()
            job = None
            info.process = None
        finally:
            if attributes_ready:
                delete_attrs(attributes)
            if job is not None:
                terminate_job(job, 1)
                fs._close(job)
                if info.process:
                    wait_handle(info.process, 5000)
                    fs._close(info.process)
                if info.thread:
                    fs._close(info.thread)
                for stream in streams:
                    stream.close()
            for handle in handles:
                fs._close(handle)

    def _reap(self):
        try:
            result = wait_handle(self._process, 0xFFFFFFFF)
            if result != 0:
                raise OSError("Windows process wait failed")
            code = D()
            check(exit_code(self._process, C.byref(code)))
            self.returncode = code.value
        except BaseException as exc:
            self._error = exc
        finally:
            with self._mutex:
                if self._job is not None:
                    # Closing kills all remaining descendants, including pipe owners.
                    fs._close(self._job)
                    self._job = None
            fs._close(self._process)
            self._done.set()

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self, timeout=None):
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        if self._error:
            raise self._error
        return self.returncode

    def terminate(self):
        with self._mutex:
            if self._job is not None:
                check(terminate_job(self._job, 1))

    kill = terminate

    def communicate(self, input=None, timeout=None):
        # For small diagnostics/tests. Shared turn streaming uses bounded readers.
        output = [None, None]
        errors = []
        def read(index, stream):
            try:
                chunks, size = [], 0
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    size += len(chunk.encode("utf-8"))
                    if size > 128 * 1024:
                        errors.append(JvError("Windows diagnostic output exceeded its limit"))
                        self.terminate()
                        return
                    chunks.append(chunk)
                output[index] = "".join(chunks)
            except (OSError, ValueError) as exc:
                errors.append(exc)
        def write():
            try:
                if input is not None:
                    self.stdin.write(input)
                self.stdin.close()
            except (OSError, ValueError):
                pass
        workers = [threading.Thread(target=read, args=(i, stream), daemon=True)
                   for i, stream in enumerate((self.stdout, self.stderr))]
        workers.append(threading.Thread(target=write, daemon=True))
        for worker in workers:
            worker.start()
        try:
            self.wait(timeout)
        except subprocess.TimeoutExpired:
            self.terminate()
            self.wait(5)
            raise
        finally:
            for worker in workers:
                worker.join(5)
            if any(worker.is_alive() for worker in workers):
                raise JvError("Windows child pipe cleanup failed")
            for stream in (self.stdin, self.stdout, self.stderr):
                stream.close()
        if errors:
            raise errors[0]
        return tuple(output)


def spawn_engine(command, env):
    return OwnedProcess(command, env)


def stop_process(process):
    if not isinstance(process, OwnedProcess):
        raise JvError("Refusing to stop a process not owned by JV CLI")
    process.terminate()
    process.wait(5)
