"""Build an unsigned, self-contained AMD64 bundle and per-user Inno installer.

Build dependencies are exact HTTPS artifacts, verified before extraction/execution.
No npm, Node, pip, runtime downloads, credentials or release publication.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'python-3.10.11-embed-amd64.zip': (
        'https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip',
        '608619f8619075629c9c69f361352a0da6ed7e62f83a0e19c63e0ea32eb7629d'),
    'codex-0.149.1-win32-x64.tgz': (
        'https://registry.npmjs.org/@openai/codex/-/codex-0.149.1-win32-x64.tgz',
        '513bde2e7a1fe31e9b7ab2c9ec1dc87e54eb93d3adc5ae579452a7f0c09e9ed2'),
    'innosetup-6.4.3.exe': (
        'https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe',
        'f3c42116542c4cc57263c5ba6c4feabfc49fe771f2f98a79d2f7628b8762723b'),
}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def obtain(name):
    url, expected = PINS[name]
    target = ROOT / 'downloads' / name
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix('.download')
        urllib.request.urlretrieve(url, temporary)
        if digest(temporary) != expected:
            temporary.unlink()
            raise RuntimeError(f'Checksum mismatch: {name}')
        temporary.replace(target)
    if target.is_symlink() or digest(target) != expected:
        raise RuntimeError(f'Checksum mismatch: {name}')
    return target


def safe_name(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or any(c in name for c in '\\:\0')
            or any(v in ('', '.', '..') or v.endswith((' ', '.')) or PureWindowsPath(v).is_reserved()
                   for v in name.split('/'))):
        raise ValueError('Unsafe archive path')
    return p


def write(path, text):
    path.write_text(text, encoding='utf-8', newline='\n')


def verify_payload(root):
    entries = {}
    for line in (root / 'PACKAGE.sha256').read_text(encoding='utf-8').splitlines():
        sha, name = line.split('  ', 1)
        safe_name(name)
        if name.casefold() in entries or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid package manifest')
        path = root / name
        for component in (path, *path.parents):
            if component == root.parent:
                break
            if component.is_symlink() or getattr(component.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Reparse point in package')
        if path.stat().st_nlink != 1 or digest(path) != sha:
            raise ValueError(f'Package verification failed: {name}')
        entries[name.casefold()] = sha
    allowed = {'package.sha256', 'unins000.exe', 'unins000.dat', 'unins000.msg'}
    actual = {p.relative_to(root).as_posix().casefold() for p in root.rglob('*') if p.is_file()}
    if actual - allowed != set(entries):
        raise ValueError('Unexpected or missing package files')
    return len(entries)


def main():
    if os.name != 'nt':
        raise SystemExit('Build Windows artifacts on native Windows only')
    import manage
    source_entries = manage.manifest(ROOT)
    version = (ROOT / 'VERSION').read_text().strip()
    assets = {name: obtain(name) for name in PINS}
    # Verify the extracted build tool against the signed, pinned installer every build
    # by extracting into a fresh repository-local portable directory.
    with tempfile.TemporaryDirectory(prefix='staging-build-', dir=ROOT) as temporary:
        stage = Path(temporary)
        compiler_dir = stage / 'compiler'
        subprocess.run([str(assets['innosetup-6.4.3.exe']), '/PORTABLE=1', '/CURRENTUSER', '/VERYSILENT',
                        '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/NOICONS', f'/DIR={compiler_dir}'], check=True)
        app = stage / 'app'
        app.mkdir()
        # Copy only the verified manifest inventory, never entire working folders:
        # ignored .env/config/debug files beside source must never enter a bundle.
        for name, expected in source_entries.items():
            if (PurePosixPath(name).parts[0] not in ('bin', 'lib', 'third_party')
                    and name not in ('VERSION', 'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md')):
                continue
            source, target = ROOT / name, app / name
            if digest(source) != expected:
                raise ValueError('Source changed after manifest verification')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        (app / 'third_party/inno-setup').mkdir()
        shutil.copyfile(compiler_dir / 'license.txt', app / 'third_party/inno-setup/LICENSE.txt')
        (app / 'python').mkdir()
        with zipfile.ZipFile(assets['python-3.10.11-embed-amd64.zip']) as archive:
            for member in archive.infolist():
                safe_name(member.filename)
                if member.is_dir() or member.external_attr >> 16 & 0o170000 == 0o120000:
                    raise ValueError('Unexpected embedded runtime entry')
                (app / 'python' / member.filename).write_bytes(archive.read(member))
        write(app / 'python/python310._pth', 'python310.zip\n.\n../lib\n')
        engine = app / 'runtime/node_modules/@openai/codex-win32-x64'
        engine.mkdir(parents=True)
        seen = set()
        with tarfile.open(assets['codex-0.149.1-win32-x64.tgz']) as archive:
            for member in archive:
                name = safe_name(member.name)
                if name.parts[0] != 'package' or len(name.parts) < 2 or not member.isfile():
                    raise ValueError('Unexpected native engine entry')
                relative = PurePosixPath(*name.parts[1:])
                if str(relative).casefold() in seen:
                    raise ValueError('Duplicate native engine entry')
                seen.add(str(relative).casefold())
                target = engine / str(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
        write(app / 'use.lock', '')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
            raise ValueError('Invalid source commit')
        write(app / 'BUILD.json', json.dumps({'version': version, 'source_commit': commit, 'engine': '0.149.1', 'python': '3.10.11',
              'architecture': 'AMD64', 'signed': False, 'source_manifest_sha256': digest(ROOT / 'MANIFEST.sha256'),
              'inputs': {n: pin[1] for n, pin in PINS.items()}}, indent=2)+'\n')
        shutil.copyfile(ROOT / 'docs/WINDOWS_INSTALL.md', app / 'WINDOWS_INSTALL.md')
        csc = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(csc), '/nologo', '/target:exe', '/platform:x64', '/optimize+',
                        f'/out:{app / "jvcli.exe"}', str(ROOT / 'packaging/windows/Launcher.cs')], check=True)
        files = sorted(p for p in app.rglob('*') if p.is_file())
        write(app / 'PACKAGE.sha256', ''.join(f'{digest(p)}  {p.relative_to(app).as_posix()}\n' for p in files))
        print(f'Package manifest: {verify_payload(app)} files', flush=True)
        dist = ROOT / 'dist'
        dist.mkdir(exist_ok=True)
        base = f'jv-cli-{version}-windows-x86_64'
        portable = dist / (base + '.zip')
        with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for p in sorted(app.rglob('*')):
                if p.is_file():
                    entry = zipfile.ZipInfo(p.relative_to(app).as_posix(), (1980,1,1,0,0,0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, p.read_bytes())
        # Exact inventory, never a recursive wildcard that could include local evidence.
        inventory = stage / 'files.iss'
        write(inventory, '\n'.join(f'Source: "{p}"; DestDir: "{{app}}\\{p.relative_to(app).parent}"; Flags: ignoreversion' for p in sorted(app.rglob('*')) if p.is_file() and p.name != 'use.lock'))
        subprocess.run([str(compiler_dir / 'ISCC.exe'), '/Qp', f'/DAppVersion={version}',
                        f'/DInventory={inventory}', f'/O{dist}', f'/F{base}-setup',
                        str(ROOT / 'packaging/windows/setup.iss')], check=True)
        outputs = [portable, dist / (base + '-setup.exe')]
        write(dist / 'SHA256SUMS.txt', ''.join(f'{digest(p)}  {p.name}\n' for p in outputs))
        for p in outputs:
            print(f'{p.name} {p.stat().st_size} bytes SHA256 {digest(p)} UNSIGNED')


if __name__ == '__main__':
    main()
