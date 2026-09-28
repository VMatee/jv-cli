#!/usr/bin/env python3
"""Build a checked Linux x86_64 offline ZIP from release source and pinned binaries."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import tempfile
import time
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import manage

NODE_VERSION = "24.21.0"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-linux-x64.tar.xz"
NODE_SHA256 = "fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6"


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def node_files(destination: Path, tarball: Path | None) -> dict[str, Path]:
    if tarball is None:
        tarball = destination / NODE_ARCHIVE
        with urlopen(
            f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}", timeout=60
        ) as response, tarball.open("wb") as stream:
            shutil.copyfileobj(response, stream)
    if digest_file(tarball) != NODE_SHA256:
        raise SystemExit("Pinned Node.js archive checksum mismatch")
    result = {}
    with tarfile.open(tarball, mode="r:xz") as archive:
        for source_name, target_name in (
            (f"node-v{NODE_VERSION}-linux-x64/bin/node", "runtime/bin/node"),
            (f"node-v{NODE_VERSION}-linux-x64/LICENSE", "runtime/NODE-LICENSE"),
        ):
            member = archive.getmember(source_name)
            if not member.isfile():
                raise SystemExit(f"Invalid Node.js archive member: {source_name}")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"Missing Node.js archive member: {source_name}")
            target = destination / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream)
            target.chmod(0o755 if target_name.endswith("/node") else 0o644)
            result[target_name] = target
    return result


def engine_files(destination: Path) -> dict[str, Path]:
    modules = ROOT / "runtime/node_modules/@openai"
    for package, expected_version in (
        ("codex", manage.ENGINE_VERSION),
        ("codex-linux-x64", f"{manage.ENGINE_VERSION}-linux-x64"),
    ):
        metadata = json.loads((modules / package / "package.json").read_text())
        if metadata.get("version") != expected_version:
            raise SystemExit(f"Installed {package} is not the pinned engine version")
    result = {}
    for package in ("codex", "codex-linux-x64"):
        package_root = modules / package
        for source in package_root.rglob("*"):
            if source.is_symlink():
                raise SystemExit("Refusing a symlink in the installed engine")
            if not source.is_file():
                continue
            relative = source.relative_to(ROOT / "runtime")
            name = (Path("runtime") / relative).as_posix()
            result[name] = source
    required = {
        "runtime/node_modules/@openai/codex/bin/codex.js",
        "runtime/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex",
    }
    if not required <= set(result):
        raise SystemExit("Installed engine package is incomplete")
    wrapper = destination / "runtime/node_modules/.bin/codex"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        '#!/bin/sh\n'
        'RUNTIME=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)\n'
        'exec "$RUNTIME/bin/node" "$RUNTIME/node_modules/@openai/codex/bin/codex.js" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result["runtime/node_modules/.bin/codex"] = wrapper
    return result


def add_file(output: zipfile.ZipFile, name: str, source: Path, stamp: tuple) -> None:
    info = zipfile.ZipInfo(name, stamp)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | stat.S_IMODE(source.stat().st_mode)) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    with source.open("rb") as input_stream, output.open(info, "w", force_zip64=True) as output_stream:
        shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-tarball", type=Path, help="Use a locally downloaded pinned Node.js tarball")
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    entries = manage.manifest(ROOT)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"jv-cli-{version}-linux-x86_64-offline.zip"
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    epoch = max(315532800, int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")))
    stamp = time.gmtime(epoch)[:6]
    with tempfile.TemporaryDirectory(prefix="jv-cli-offline-build-") as temp:
        temporary = Path(temp)
        files = node_files(temporary, args.node_tarball)
        files.update(engine_files(temporary))
        offline_manifest = temporary / "offline-manifest.sha256"
        offline_manifest.write_text(
            "".join(f"{digest_file(source)}  {name}\n" for name, source in sorted(files.items())),
            encoding="ascii",
        )
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for name in [*entries, "MANIFEST.sha256"]:
                add_file(output, f"jv-cli/{name}", ROOT / name, stamp)
            for name, source in sorted(files.items()):
                add_file(output, f"jv-cli/offline/{name}", source, stamp)
            add_file(output, "jv-cli/offline/MANIFEST.sha256", offline_manifest, stamp)
    checksum.write_text(f"{digest_file(archive)}  {archive.name}\n", encoding="ascii")
    print(archive)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
