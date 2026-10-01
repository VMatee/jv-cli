"""ACL setup for disposable, repository-local native test fixtures only."""
import ctypes as C
from pathlib import Path


def trusted_fixture_directory(path):
    from jvcli.platform import _windows_fs as fs
    path = Path(path).resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    if path.parent != root or not path.name.startswith("staging-"):
        raise ValueError("Only disposable repository fixture roots may be prepared")
    # Hosted runners can grant other users write access to their workspace.
    # Construct the test's trusted parent explicitly; never relax product checks
    # or modify the checkout, installed Python, or the user's directories.
    sd = fs.P()
    sddl = f"D:P(A;OICI;FA;;;{fs.user_sid()})(A;OICI;FA;;;SY)(A;OICI;FR;;;WD)"
    fs._check(fs._sddl(sddl, 1, C.byref(sd), None))
    set_security = fs._api(fs.A, "SetFileSecurityW", fs.W.BOOL, fs.W.LPCWSTR, fs.D, fs.P)
    try:
        fs._check(set_security(str(path), 0x80000004, sd))
    finally:
        fs._free(sd)
