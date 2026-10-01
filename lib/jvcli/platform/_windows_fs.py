"""Native private state on local NTFS. Imported only on Windows.

Security is attached at creation, then checked on the opened object. Ancestor
handles deny delete sharing; each child is opened relative to its pinned parent.
Existing non-private objects are rejected, never silently repaired or truncated. This does
not defend against another process running as the same user or an administrator.
"""
from __future__ import annotations

import contextlib
import ctypes as C
from ctypes import wintypes as W
import errno
import msvcrt
import os
from pathlib import Path
import uuid

from .common import windows_state_path
from ..safety import JvError

K = C.WinDLL("kernel32", use_last_error=True)
A = C.WinDLL("advapi32", use_last_error=True)
N = C.WinDLL("ntdll")
P = C.c_void_p
D = W.DWORD


def _api(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, args
    return fn


class SecurityAttributes(C.Structure):
    _fields_ = [("length", D), ("descriptor", P), ("inherit", W.BOOL)]


class FileInfo(C.Structure):
    _fields_ = [("attributes", D), ("creation", W.FILETIME),
                ("access", W.FILETIME), ("write", W.FILETIME),
                ("volume", D), ("size_high", D), ("size_low", D),
                ("links", D), ("index_high", D), ("index_low", D)]


class Acl(C.Structure):
    _fields_ = [("revision", W.BYTE), ("reserved", W.BYTE),
                ("size", W.WORD), ("count", W.WORD), ("reserved2", W.WORD)]


class Overlapped(C.Structure):
    _fields_ = [("internal", C.c_size_t), ("internal_high", C.c_size_t),
                ("offset", D), ("offset_high", D), ("event", W.HANDLE)]


_close = _api(K, "CloseHandle", W.BOOL, W.HANDLE)
_free = _api(K, "LocalFree", P, P)
_create = _api(K, "CreateFileW", W.HANDLE, W.LPCWSTR, D, D,
               C.POINTER(SecurityAttributes), D, D, W.HANDLE)
_info = _api(K, "GetFileInformationByHandle", W.BOOL, W.HANDLE, C.POINTER(FileInfo))
_security = _api(A, "GetSecurityInfo", D, W.HANDLE, D, D,
                 C.POINTER(P), C.POINTER(P), C.POINTER(P), C.POINTER(P), C.POINTER(P))
_control = _api(A, "GetSecurityDescriptorControl", W.BOOL, P, C.POINTER(W.WORD), C.POINTER(D))
_ace = _api(A, "GetAce", W.BOOL, P, D, C.POINTER(P))
_sid_string = _api(A, "ConvertSidToStringSidW", W.BOOL, P, C.POINTER(P))
_sddl = _api(A, "ConvertStringSecurityDescriptorToSecurityDescriptorW", W.BOOL,
             W.LPCWSTR, D, C.POINTER(P), C.POINTER(D))
_process = _api(K, "GetCurrentProcess", W.HANDLE)
_token = _api(A, "OpenProcessToken", W.BOOL, W.HANDLE, D, C.POINTER(W.HANDLE))
_token_info = _api(A, "GetTokenInformation", W.BOOL, W.HANDLE, D, P, D, C.POINTER(D))
_volume = _api(K, "GetVolumeInformationW", W.BOOL, W.LPCWSTR, W.LPWSTR, D,
               C.POINTER(D), C.POINTER(D), C.POINTER(D), W.LPWSTR, D)
_drive = _api(K, "GetDriveTypeW", D, W.LPCWSTR)
_final = _api(K, "GetFinalPathNameByHandleW", D, W.HANDLE, W.LPWSTR, D, D)
_lock = _api(K, "LockFileEx", W.BOOL, W.HANDLE, D, D, D, D, C.POINTER(Overlapped))


class UnicodeString(C.Structure):
    _fields_ = [("length", W.USHORT), ("maximum", W.USHORT), ("buffer", P)]


class ObjectAttributes(C.Structure):
    _fields_ = [("length", D), ("root", W.HANDLE),
                ("name", C.POINTER(UnicodeString)), ("attributes", D),
                ("security", P), ("qos", P)]


class IoStatus(C.Structure):
    _fields_ = [("status", P), ("information", C.c_size_t)]


_ntcreate = _api(N, "NtCreateFile", W.LONG, C.POINTER(W.HANDLE), D,
                 C.POINTER(ObjectAttributes), C.POINTER(IoStatus), P,
                 D, D, D, D, P, D)
_ntset = _api(N, "NtSetInformationFile", W.LONG, W.HANDLE,
              C.POINTER(IoStatus), P, D, D)
_nt_error = _api(N, "RtlNtStatusToDosError", D, W.LONG)


def ntcheck(status):
    if status < 0:
        # Reparse encountered with OBJ_DONT_REPARSE is a policy rejection.
        if status & 0xFFFFFFFF == 0xC000050B:
            raise JvError("Windows state must not traverse reparse points")
        raise C.WinError(_nt_error(status))


def relative_open(parent, name, *, directory=False, creation=1,
                  access=0x20081, share=3, sa=None, write_through=False):
    # A single lexical component: no Win32 normalization or intermediate reparse.
    if not name or any(c in name for c in "\\/:\x00") or name in {".", ".."}:
        raise JvError("Unsafe relative Windows state name")
    buf = C.create_unicode_buffer(name)
    size = len(name.encode("utf-16-le"))
    text = UnicodeString(size, size + 2, C.cast(buf, P))
    attrs = ObjectAttributes(C.sizeof(ObjectAttributes), parent, C.pointer(text),
                             0x1040, sa.descriptor if sa else None, None)  # DONT_REPARSE | CASE_INSENSITIVE
    handle, io = W.HANDLE(), IoStatus()
    ntcheck(_ntcreate(C.byref(handle), access | 0x100000, C.byref(attrs), C.byref(io),
                      None, 0, share, creation,
                      0x200020 | (1 if directory else 0x40) | (2 if write_through else 0), None, 0))
    return handle.value, io.information


def rename_file(handle, parent, name):
    class Rename(C.Structure):
        _fields_ = [("replace", W.BOOLEAN), ("root", W.HANDLE),
                    ("length", D), ("name", W.WCHAR * (len(name.encode("utf-16-le")) // 2 + 1))]
    rename = Rename(True, parent, len(name.encode("utf-16-le")), name)
    io = IoStatus()
    ntcheck(_ntset(handle, C.byref(io), C.byref(rename), C.sizeof(rename), 10))


def delete_file(handle):
    value, io = W.BOOLEAN(True), IoStatus()
    ntcheck(_ntset(handle, C.byref(io), C.byref(value), C.sizeof(value), 13))


READ_CONTROL = 0x20000
FULL = 0x1F01FF
INVALID = C.c_void_p(-1).value


def _check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())
    return ok


def sid_text(sid):
    value = P()
    _check(_sid_string(sid, C.byref(value)))
    try:
        return C.wstring_at(value)
    finally:
        _free(value)


def user_sid():
    token = W.HANDLE()
    _check(_token(_process(), 8, C.byref(token)))
    try:
        size = D()
        _token_info(token, 1, None, 0, C.byref(size))
        buf = C.create_string_buffer(size.value)
        _check(_token_info(token, 1, buf, size, C.byref(size)))
        return sid_text(C.cast(buf, C.POINTER(P))[0])
    finally:
        _close(token)


@contextlib.contextmanager
def descriptor(directory=False, *, public=False):
    sid = user_sid()
    flags = "OICI" if directory else ""
    sd = P()
    readers = "(A;;FR;;;WD)" if public else ""
    _check(_sddl(f"O:{sid}D:P(A;{flags};FA;;;{sid})(A;{flags};FA;;;SY){readers}",
                 1, C.byref(sd), None))
    try:
        yield SecurityAttributes(C.sizeof(SecurityAttributes), sd, False)
    finally:
        _free(sd)


def inspect(handle, *, directory=False, private=False):
    info = FileInfo()
    _check(_info(handle, C.byref(info)))
    if info.attributes & 0x400:
        raise JvError("Windows state must not traverse reparse points")
    if bool(info.attributes & 0x10) != directory:
        raise JvError("Unexpected Windows state object type")
    if not directory and info.links != 1:
        raise JvError("Windows state must not use hard-linked files")
    if private:
        owner, acl, sd = P(), P(), P()
        result = _security(handle, 1, 5, C.byref(owner), None, C.byref(acl), None, C.byref(sd))
        if result:
            raise C.WinError(result)
        try:
            current = user_sid()
            control, revision = W.WORD(), D()
            _check(_control(sd, C.byref(control), C.byref(revision)))
            if sid_text(owner) != current or not acl or not control.value & 0x1000:
                raise JvError("Windows state requires a user-owned protected private DACL")
            entries = C.cast(acl, C.POINTER(Acl)).contents
            seen = set()
            for index in range(entries.count):
                ace = P()
                _check(_ace(acl, index, C.byref(ace)))
                header = C.string_at(ace, 4)
                mask = D.from_address(ace.value + 4).value
                # Accept only explicit allow ACEs for the user and LocalSystem.
                # Unknown/object/callback ACEs and inherit-only grants fail closed.
                if header[0] != 0 or header[1] & ~3 or mask != FULL:
                    raise JvError("Windows state has an unsupported private DACL")
                identity = sid_text(ace.value + 8)
                if identity not in {current, "S-1-5-18"} or identity in seen:
                    raise JvError("Windows state grants access outside its private policy")
                seen.add(identity)
            if seen != {current, "S-1-5-18"}:
                raise JvError("Windows state private DACL is incomplete")
        finally:
            _free(sd)
    return info


def inspect_public(handle, *, directory=False):
    """Public bytes may be readable, but only the user/system/admin may modify.

    Existing inherited ACLs are permitted when their effective grants satisfy
    this policy. Unknown ACE types fail closed. No ACL is silently repaired.
    """
    inspect(handle, directory=directory)
    owner, acl, sd = P(), P(), P()
    result = _security(handle, 1, 5, C.byref(owner), None, C.byref(acl), None, C.byref(sd))
    if result:
        raise C.WinError(result)
    try:
        trusted = {user_sid(), "S-1-5-18", "S-1-5-32-544"}
        if not owner or sid_text(owner) not in trusted or not acl:
            raise JvError("Windows public files require trusted ownership and a DACL")
        entries = C.cast(acl, C.POINTER(Acl)).contents
        for index in range(entries.count):
            ace = P()
            _check(_ace(acl, index, C.byref(ace)))
            header = C.string_at(ace, 4)
            if header[0] not in (0, 1) or header[1] & ~0x1F:
                raise JvError("Windows public file has an unsupported ACL")
            if header[0] == 1 or header[1] & 8:  # deny / inherit-only
                continue
            mask = D.from_address(ace.value + 4).value
            # FILE_GENERIC_READ | FILE_GENERIC_EXECUTE. Unknown/generic rights
            # are rejected rather than guessed; queried filesystem masks map them.
            if sid_text(ace.value + 8) not in trusted and mask & ~0x1200A9:
                raise JvError("Windows public files must not grant untrusted write access")
    finally:
        _free(sd)


def native_path(path):
    # Validate before normalization, which would otherwise erase '..'.
    value = str(path)
    if not Path(value).is_absolute():
        value = str(Path.cwd() / value)
    path = Path(windows_state_path({"JVCLI_HOME": value}))
    if str(path).startswith("\\\\"):
        raise JvError("Windows private state currently requires local NTFS; UNC is unsupported")
    root = path.anchor
    fs, flags = C.create_unicode_buffer(32), D()
    if _drive(root) != 3:
        raise JvError("Windows private state requires a fixed local NTFS volume")
    _check(_volume(root, None, 0, None, None, C.byref(flags), fs, len(fs)))
    if fs.value != "NTFS" or not flags.value & 8:
        raise JvError("Windows private state requires persistent NTFS ACLs")
    return path


def extended(path):
    return "\\\\?\\" + str(path)


def open_handle(path, access=READ_CONTROL | 0x81, share=1, creation=3, sa=None):
    handle = _create(extended(path), access, share, C.byref(sa) if sa else None,
                     creation, 0x02200000, None)  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
    if handle == INVALID:
        raise C.WinError(C.get_last_error())
    return handle


@contextlib.contextmanager
def ancestors(path, *, create=False):
    """Open each component relative to its parent; hold all against rename."""
    handles = []
    try:
        root = Path(path.anchor)
        handle = open_handle(root, share=3)
        handles.append(handle)
        inspect(handle, directory=True)
        buf = C.create_unicode_buffer(32768)
        length = _check(_final(handle, buf, len(buf), 0))
        if length >= len(buf) or buf.value.casefold() != extended(root).casefold():
            raise JvError("Windows state does not support substituted drive roots")
        for name in path.parts[1:-1]:
            with descriptor(True) as sa:
                handle, disposition = relative_open(handles[-1], name, directory=True,
                                                    creation=3 if create else 1, sa=sa)
            handles.append(handle)
            inspect(handle, directory=True, private=disposition == 2)
        yield handles
    finally:
        for handle in reversed(handles):
            _close(handle)


def no_symlink_path(path):
    path = native_path(path)
    # Point-in-time check only. Sensitive operations reacquire pinned handles.
    if path == Path(path.anchor):
        with ancestors(path):
            return path
    try:
        with ancestors(path) as parents:
            # Permit either object type, retaining the same no-reparse primitive.
            for directory in (False, True):
                try:
                    handle, _ = relative_open(parents[-1], path.name, directory=directory)
                except OSError as exc:
                    if not directory and exc.winerror == 5:
                        continue
                    raise
                try:
                    inspect(handle, directory=directory)
                finally:
                    _close(handle)
                break
    except FileNotFoundError:
        pass
    return path


def private_dir(path):
    path = native_path(path)
    if path == Path(path.anchor):
        raise JvError("A volume root cannot be private state")
    with ancestors(path, create=True) as parents:
        with descriptor(True) as sa:
            handle, _ = relative_open(parents[-1], path.name, directory=True, creation=3, sa=sa)
        try:
            inspect(handle, directory=True, private=True)
        finally:
            _close(handle)
    return path


def _file(parent, name, *, create=False, write=False, share=1):
    with descriptor() as sa:
        handle, _ = relative_open(parent, name,
                                  access=READ_CONTROL | (0xC0000000 if write else 0x80000000),
                                  share=share, creation=3 if create else 1, sa=sa)
    try:
        inspect(handle, private=True)
    except BaseException:
        _close(handle)
        raise
    return handle


def open_private_read(path):
    path = native_path(path)
    with ancestors(path) as parents:
        handle = _file(parents[-1], path.name)
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _close(handle)
            raise


def open_public_read(path):
    path = native_path(path)
    with ancestors(path) as parents:
        inspect_public(parents[-1], directory=True)
        handle, _ = relative_open(parents[-1], path.name, access=0x80020000, share=1)
        try:
            inspect_public(handle)
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _close(handle)
            raise


def atomic_write(path, text, mode=0o600, *, durable=False):
    if mode not in (0o600, 0o644):
        raise JvError("Unsupported Windows file ACL policy")
    public = mode == 0o644
    path = native_path(path)
    if not public:
        private_dir(path.parent)
    with ancestors(path) as parents:
        if public:
            inspect_public(parents[-1], directory=True)
        else:
            inspect(parents[-1], directory=True, private=True)
        try:
            if public:
                target, _ = relative_open(parents[-1], path.name)
            else:
                target = _file(parents[-1], path.name)
        except FileNotFoundError:
            pass
        else:
            try:
                if public:
                    inspect_public(target)
            finally:
                _close(target)
        with descriptor(public=public) as sa:
            handle, _ = relative_open(parents[-1], ".jv-write-" + uuid.uuid4().hex,
                                      access=0xC0030000, share=0, creation=2, sa=sa,
                                      write_through=durable)
        fd = None
        renamed = False
        try:
            if public:
                inspect_public(handle)
            else:
                inspect(handle, private=True)
            fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
            data = text.encode("utf-8")
            while data:
                count = os.write(fd, data)
                if not count:
                    raise OSError("Short Windows state write")
                data = data[count:]
            os.fsync(fd)
            rename_file(handle, parents[-1], path.name)
            renamed = True
            if durable:
                # NTFS write-through applies to the handle's rename metadata as
                # well as data. Flush the renamed handle before acknowledging.
                # Failure here is uncertain durability, never success or rollback.
                os.fsync(fd)
        finally:
            try:
                if not renamed:
                    delete_file(handle)
            finally:
                if fd is None:
                    _close(handle)
                else:
                    os.close(fd)


class LockHandle:
    def __init__(self, handle, parents):
        self.handle, self.parents = handle, parents
        self.locked = False


def open_lock(path, *, create=True):
    path = native_path(path)
    parents = ancestors(path)
    pinned = parents.__enter__()
    try:
        inspect(pinned[-1], directory=True, private=True)
        handle = _file(pinned[-1], path.name, create=create, write=True, share=3)
        return LockHandle(handle, parents)
    except BaseException:
        parents.__exit__(None, None, None)
        raise


def lock_file(owner, *, shared=False):
    if owner.handle is None or owner.locked:
        raise ValueError("Lock handle is closed or already locked")
    overlapped = Overlapped()
    if not _lock(owner.handle, 1 | (0 if shared else 2), 0, 1, 0, C.byref(overlapped)):
        code = C.get_last_error()
        if code == 33:
            raise BlockingIOError(errno.EAGAIN, "JV CLI state is already locked")
        raise C.WinError(code)
    owner.locked = True


def close_lock(owner):
    if owner.handle is not None:
        _check(_close(owner.handle))
        owner.handle = None
        owner.parents.__exit__(None, None, None)
