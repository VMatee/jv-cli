#!/usr/bin/env python3
"""Build a deterministic JV CLI source release for Linux x86_64."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import manage


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not version or any(ch not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for ch in version):
        raise SystemExit("Invalid VERSION")
    manage.write_manifest(ROOT)
    entries = manage.manifest(ROOT)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"jv-cli-{version}-linux-x86_64.zip"
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    epoch = max(315532800, int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")))
    stamp = time.gmtime(epoch)[:6]
    with tempfile.TemporaryDirectory(prefix="jv-cli-release-") as temporary:
        package = Path(temporary) / "jv-cli"
        package.mkdir()
        for name in [*entries, "MANIFEST.sha256"]:
            source, target = ROOT / name, package / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for path in sorted(package.rglob("*"), key=lambda item: item.as_posix()):
                if not path.is_file():
                    continue
                relative = path.relative_to(Path(temporary)).as_posix()
                info = zipfile.ZipInfo(relative, stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                executable = path.name == "jvcli" or path.suffix == ".sh" or path.parent.name == "bin"
                info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
                output.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(archive)
    print(checksum)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
