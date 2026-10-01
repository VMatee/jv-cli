"""Real local Windows ACL and kernel lock tests. Synthetic repository-local state."""
import ctypes as C
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli.platform import windows
from jvcli.safety import JvError, read_private_json

if os.name == "nt":
    from jvcli.platform import _windows_fs as fs
    import _winapi


@unittest.skipUnless(os.name == "nt", "Requires real native Windows ACLs and LockFileEx")
class NativeWindowsState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="staging-native-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = windows.private_dir(self.root / "private")

    def set_acl(self, path, sddl):
        sd = fs.P()
        fs._check(fs._sddl(sddl, 1, C.byref(sd), None))
        set_security = fs._api(fs.A, "SetFileSecurityW", fs.W.BOOL, fs.W.LPCWSTR, fs.D, fs.P)
        try:
            fs._check(set_security(str(path), 0x80000004, sd))
        finally:
            fs._free(sd)

    def child(self, body, *args):
        prelude = "import sys; sys.path.insert(0,sys.argv[1]); from jvcli.platform import windows as w; "
        return subprocess.run([sys.executable, "-B", "-c", prelude + body,
                               str(ROOT / "lib"), *map(str, args)],
                              capture_output=True, text=True, timeout=15, shell=False)

    def probe(self, path, shared=False):
        result = self.child(
            "h=w.open_lock(sys.argv[2],create=False)\n"
            "try:\n w.lock_file(h,shared=sys.argv[3]=='shared'); print('acquired')\n"
            "except BlockingIOError:\n print('blocked')\n"
            "finally:\n w.close_lock(h)\n", path, "shared" if shared else "exclusive")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_new_and_existing_private_directory(self):
        self.assertEqual(windows.private_dir(self.private), self.private)
        handle = fs.open_handle(self.private)
        try:
            fs.inspect(handle, directory=True, private=True)
        finally:
            fs._close(handle)

    def test_nested_private_directories(self):
        path = self.private / "one" / "two" / "three"
        windows.private_dir(path)
        for part in (path, path.parent, path.parent.parent):
            self.assertEqual(windows.private_dir(part), part)

    def test_existing_inherited_directory_rejected_without_repair(self):
        path = self.root / "inherited"
        path.mkdir()
        with self.assertRaises(JvError):
            windows.private_dir(path)
        self.assertTrue(path.is_dir())

    def test_explicit_other_user_access_rejected(self):
        self.set_acl(self.private, f"D:P(A;OICI;FA;;;{fs.user_sid()})(A;OICI;FA;;;SY)(A;;FR;;;WD)")
        with self.assertRaises(JvError):
            windows.private_dir(self.private)

    def test_null_dacl_rejected(self):
        self.set_acl(self.private, "D:NO_ACCESS_CONTROL")
        with self.assertRaises(JvError):
            windows.private_dir(self.private)

    def test_kernel_denies_read_to_restricted_token(self):
        path = self.private / "file"
        windows.atomic_write(path, "synthetic")
        windows.atomic_write(self.private / "public", "public", mode=0o644)
        class SidAttributes(C.Structure):
            _fields_ = [("sid", fs.P), ("attributes", fs.D)]
        convert = fs._api(fs.A, "ConvertStringSidToSidW", fs.W.BOOL,
                          fs.W.LPCWSTR, C.POINTER(fs.P))
        restrict = fs._api(fs.A, "CreateRestrictedToken", fs.W.BOOL,
                           fs.W.HANDLE, fs.D, fs.D, fs.P, fs.D, fs.P,
                           fs.D, fs.P, C.POINTER(fs.W.HANDLE))
        impersonate = fs._api(fs.A, "ImpersonateLoggedOnUser", fs.W.BOOL, fs.W.HANDLE)
        revert = fs._api(fs.A, "RevertToSelf", fs.W.BOOL)
        token, restricted, everyone = fs.W.HANDLE(), fs.W.HANDLE(), fs.P()
        fs._check(fs._token(fs._process(), 0xA, C.byref(token)))
        try:
            fs._check(convert("S-1-1-0", C.byref(everyone)))
            sid = SidAttributes(everyone, 0)
            fs._check(restrict(token, 1, 0, None, 0, None, 1, C.byref(sid), C.byref(restricted)))
            # Pin the parent before impersonation to test the file's own DACL.
            with fs.ancestors(path) as parents:
                fs._check(impersonate(restricted))
                try:
                    with self.assertRaises(PermissionError):
                        fs.relative_open(parents[-1], path.name, access=0x80000000)
                    readable, _ = fs.relative_open(parents[-1], "public", access=0x80000000)
                    fs._close(readable)
                    with self.assertRaises(PermissionError):
                        fs.relative_open(parents[-1], "public", access=0x40000000)
                finally:
                    fs._check(revert())
        finally:
            if restricted:
                fs._close(restricted)
            if everyone:
                fs._free(everyone)
            fs._close(token)

    def test_inherit_only_private_grant_rejected(self):
        self.set_acl(self.private, f"D:P(A;OICIIO;FA;;;{fs.user_sid()})(A;OICI;FA;;;SY)")
        try:
            with self.assertRaises((JvError, OSError)):
                windows.private_dir(self.private)
        finally:
            self.set_acl(self.private, f"D:P(A;OICI;FA;;;{fs.user_sid()})(A;OICI;FA;;;SY)")

    def test_lock_handle_is_not_inheritable(self):
        owner = windows.open_lock(self.private / "lock")
        try:
            flags = fs.D()
            info = fs._api(fs.K, "GetHandleInformation", fs.W.BOOL, fs.W.HANDLE, C.POINTER(fs.D))
            fs._check(info(owner.handle, C.byref(flags)))
            self.assertEqual(flags.value & 1, 0)
        finally:
            windows.close_lock(owner)

    def test_new_file_replace_utf8_and_no_temporary_residue(self):
        path = self.private / "state.json"
        windows.atomic_write(path, '{"value":"first"}')
        windows.atomic_write(path, '{"value":"ภาษาไทย é 😀"}')
        self.assertEqual(read_private_json(path), {"value": "ภาษาไทย é 😀"})
        self.assertEqual(list(self.private.iterdir()), [path])

    def test_spaces_thai_unicode_and_long_path(self):
        path = self.private / "พื้นที่ ทดสอบ é 😀" / ("long-segment" * 12) / "state.json"
        windows.atomic_write(path, '{"ok":true}')
        self.assertEqual(read_private_json(path), {"ok": True})

    def test_case_alias(self):
        path = self.private / "MiXeD.json"
        windows.atomic_write(path, '{"ok":true}')
        self.assertEqual(read_private_json(Path(str(path).upper())), {"ok": True})

    def test_unsafe_existing_file_never_read_or_replaced(self):
        path = self.private / "unsafe"
        windows.atomic_write(path, "original synthetic content")
        self.set_acl(path, f"D:P(A;;FA;;;{fs.user_sid()})(A;;FA;;;SY)(A;;FR;;;WD)")
        with self.assertRaises(JvError):
            windows.open_private_read(path)
        with self.assertRaises(JvError):
            windows.atomic_write(path, "replacement")
        self.assertEqual(path.read_text(), "original synthetic content")

    def test_inherited_file_rejected(self):
        path = self.private / "inherited"
        path.write_text("synthetic")
        with self.assertRaises(JvError):
            windows.open_private_read(path)

    def test_missing_read_and_noncreating_lock(self):
        path = self.private / "missing"
        self.assertEqual(read_private_json(path), {})
        with self.assertRaises(FileNotFoundError):
            windows.open_lock(path, create=False)
        self.assertFalse(path.exists())

    def test_wrong_object_type_rejected(self):
        with self.assertRaises((JvError, OSError)):
            windows.open_private_read(self.private)
        with self.assertRaises((JvError, OSError)):
            windows.atomic_write(self.private, "synthetic")

    def test_hard_link_rejected(self):
        path = self.private / "file"
        windows.atomic_write(path, "synthetic")
        os.link(path, self.private / "alias")
        with self.assertRaises(JvError):
            windows.open_private_read(path)
        with self.assertRaises(JvError):
            windows.atomic_write(path, "replacement")

    def test_junction_ancestor_and_final_rejected(self):
        outside = windows.private_dir(self.root / "outside")
        junction = self.private / "junction"
        _winapi.CreateJunction(str(outside), str(junction))
        try:
            for action in (lambda: windows.private_dir(junction),
                           lambda: windows.atomic_write(junction / "secret", "synthetic"),
                           lambda: windows.open_private_read(junction / "secret"),
                           lambda: windows.open_lock(junction / "lock"),
                           lambda: windows.no_symlink_path(junction / "missing" / "leaf")):
                with self.assertRaises(JvError):
                    action()
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            junction.rmdir()

    def test_ancestor_pinned_against_rename(self):
        with fs.ancestors(self.private / "file"):
            with self.assertRaises(OSError):
                os.replace(self.private, self.root / "renamed")

    def test_reparse_mutation_after_parent_open_never_redirects_write(self):
        outside = windows.private_dir(self.root / "outside")
        device_io = fs._api(fs.K, "DeviceIoControl", fs.W.BOOL,
                            fs.W.HANDLE, fs.D, fs.P, fs.D, fs.P, fs.D,
                            C.POINTER(fs.D), fs.P)
        writer = fs.open_handle(self.private, access=0x40000000, share=3)
        target = ("\\??\\" + str(outside)).encode("utf-16-le")
        names = target + b"\x00\x00" + target + b"\x00\x00"
        data = struct.pack("<IHHHHHH", 0xA0000003, 8 + len(names), 0,
                           0, len(target), len(target) + 2, len(target)) + names
        returned = fs.D()
        mutated = False
        original = fs.relative_open

        def mutate(parent, name, **kwargs):
            nonlocal mutated
            if name.startswith(".jv-write-") and not mutated:
                fs._check(device_io(writer, 0x900A4, data, len(data), None, 0,
                                    C.byref(returned), None))
                mutated = True
            return original(parent, name, **kwargs)

        try:
            with patch.object(fs, "relative_open", side_effect=mutate):
                try:
                    windows.atomic_write(self.private / "file", "synthetic")
                except (JvError, OSError):
                    pass  # Rejecting a changed ancestor is also safe.
            self.assertTrue(mutated)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            if mutated:
                delete = struct.pack("<IHH", 0xA0000003, 0, 0)
                fs._check(device_io(writer, 0x900AC, delete, len(delete), None, 0,
                                    C.byref(returned), None))
            fs._close(writer)

    def test_ambiguous_and_remote_paths_rejected(self):
        for path in (str(self.private / "file") + ":stream", str(self.private / "CON"),
                     str(self.private / "trailing."), r"\\server\share\state"):
            with self.subTest(path=path), self.assertRaises(JvError):
                windows.atomic_write(path, "synthetic")

    def test_public_mode_is_not_admitted_as_private(self):
        path = self.private / "manifest"
        windows.atomic_write(path, "public", mode=0o644)
        with self.assertRaises(JvError):
            windows.open_private_read(path)
        with self.assertRaises(JvError):
            windows.atomic_write(path, "private")

    def test_public_file_new_and_replacement_in_inherited_parent(self):
        path = self.root / "manifest"
        windows.atomic_write(path, "first", mode=0o644)
        windows.atomic_write(path, "second", mode=0o644)
        fd = fs.open_public_read(path)
        with os.fdopen(fd, "rb") as stream:
            self.assertEqual(stream.read(), b"second")

    def test_public_file_accepts_existing_trusted_inherited_acl(self):
        path = self.root / "manifest"
        path.write_text("first")
        windows.atomic_write(path, "second", mode=0o644)
        self.assertEqual(path.read_text(), "second")

    def test_public_file_rejects_untrusted_write_grants(self):
        path = self.root / "manifest"
        path.write_text("first")
        self.set_acl(path, f"D:P(A;;FA;;;{fs.user_sid()})(A;;FA;;;SY)(A;;FW;;;WD)")
        with self.assertRaises(JvError):
            windows.atomic_write(path, "second", mode=0o644)
        with self.assertRaises(JvError):
            fs.open_public_read(path)
        self.assertEqual(path.read_text(), "first")

    def test_public_file_rejects_writable_parent(self):
        self.set_acl(self.private, f"D:P(A;OICI;FA;;;{fs.user_sid()})(A;OICI;FA;;;SY)(A;;FW;;;WD)")
        with self.assertRaises(JvError):
            windows.atomic_write(self.private / "manifest", "public", mode=0o644)
        self.assertEqual(list(self.private.iterdir()), [])

    def test_public_file_rejects_hardlink_and_junction(self):
        path = self.private / "manifest"
        windows.atomic_write(path, "first", mode=0o644)
        os.link(path, self.private / "alias")
        with self.assertRaises(JvError):
            windows.atomic_write(path, "second", mode=0o644)
        junction = self.root / "junction"
        _winapi.CreateJunction(str(self.private), str(junction))
        try:
            with self.assertRaises(JvError):
                windows.atomic_write(junction / "other", "public", mode=0o644)
        finally:
            junction.rmdir()

    def test_public_file_failure_preserves_original(self):
        path = self.root / "manifest"
        windows.atomic_write(path, "first", mode=0o644)
        with patch.object(fs, "rename_file", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                windows.atomic_write(path, "second", mode=0o644)
        self.assertEqual(path.read_text(), "first")
        self.assertFalse(list(self.root.glob(".jv-write-*")))

    def test_unsupported_file_mode_is_rejected(self):
        with self.assertRaises(JvError):
            windows.atomic_write(self.root / "manifest", "public", mode=0o666)

    def test_write_failure_preserves_old_file_and_cleans_temporary(self):
        path = self.private / "file"
        windows.atomic_write(path, "original")
        with patch.object(fs.os, "fsync", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                windows.atomic_write(path, "replacement")
        self.assertEqual(path.read_text(), "original")
        self.assertEqual(list(self.private.iterdir()), [path])

    def test_read_handle_blocks_replacement_until_closed(self):
        path = self.private / "file"
        windows.atomic_write(path, "original")
        fd = windows.open_private_read(path)
        try:
            with self.assertRaises(OSError):
                windows.atomic_write(path, "replacement")
            self.assertEqual(os.read(fd, 100), b"original")
        finally:
            os.close(fd)
        windows.atomic_write(path, "replacement")

    def test_exclusive_lock_competing_process(self):
        path = self.private / "lock"
        owner = windows.open_lock(path)
        try:
            windows.lock_file(owner)
            self.assertEqual(self.probe(path), "blocked")
            self.assertEqual(self.probe(path, shared=True), "blocked")
        finally:
            windows.close_lock(owner)
        self.assertEqual(self.probe(path), "acquired")

    def test_shared_locks_coexist_and_reject_writer(self):
        path = self.private / "lock"
        owner = windows.open_lock(path)
        try:
            windows.lock_file(owner, shared=True)
            self.assertEqual(self.probe(path, shared=True), "acquired")
            self.assertEqual(self.probe(path), "blocked")
        finally:
            windows.close_lock(owner)

    def test_lock_cannot_be_replaced_while_owned(self):
        path = self.private / "lock"
        owner = windows.open_lock(path)
        try:
            windows.lock_file(owner)
            with self.assertRaises(OSError):
                path.unlink()
            with self.assertRaises(OSError):
                windows.atomic_write(path, "synthetic corrupt metadata")
            self.assertEqual(self.probe(path), "blocked")
        finally:
            windows.close_lock(owner)

    def test_corrupt_metadata_does_not_affect_lock_ownership(self):
        path = self.private / "lock"
        windows.atomic_write(path, "{corrupt synthetic metadata")
        owner = windows.open_lock(path)
        try:
            windows.lock_file(owner)
            self.assertEqual(self.probe(path), "blocked")
        finally:
            windows.close_lock(owner)

    def test_process_death_releases_lock(self):
        path = self.private / "lock"
        script = ("import sys; sys.path.insert(0,sys.argv[1]); "
                  "from jvcli.platform import windows as w; h=w.open_lock(sys.argv[2]); "
                  "w.lock_file(h); print('ready',flush=True); sys.stdin.buffer.read(1)")
        child = subprocess.Popen([sys.executable, "-B", "-c", script, str(ROOT / "lib"), str(path)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 shell=False)
        try:
            self.assertEqual(child.stdout.readline(), b"ready\r\n")
            self.assertEqual(self.probe(path), "blocked")
            child.kill()
            child.wait(timeout=10)
            self.assertEqual(self.probe(path), "acquired")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    def test_exception_cleanup_and_double_close(self):
        path = self.private / "lock"
        owner = windows.open_lock(path)
        try:
            windows.lock_file(owner)
            with self.assertRaises(ValueError):
                windows.lock_file(owner)
        finally:
            windows.close_lock(owner)
        windows.close_lock(owner)
        with self.assertRaises(ValueError):
            windows.lock_file(owner)
        self.assertEqual(self.probe(path), "acquired")

    def test_failed_open_releases_ancestor_handles(self):
        for _ in range(10):
            with self.assertRaises(FileNotFoundError):
                windows.open_lock(self.private / "missing", create=False)
        os.replace(self.private, self.root / "renamed")


if __name__ == "__main__":
    unittest.main()
