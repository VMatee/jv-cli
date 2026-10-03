#!/usr/bin/env python3
"""Exact cross-platform release inventory and byte verification; no credentials."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def identity(version, commit):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid release identity')


def names(version, platform):
    if platform == 'windows':
        base = f'jv-cli-{version}-windows-x86_64'
        return [base + '.zip', base + '-setup.exe']
    if platform == 'linux':
        base = f'jv-cli-{version}-linux-x86_64'
        return [base + '.zip', base + '.zip.sha256', base + '-offline.zip', base + '-offline.zip.sha256']
    if platform == 'all':
        return names(version, 'linux') + names(version, 'windows')
    raise ValueError('Unsupported release platform')


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Unsafe release file')
    if info.st_size <= 0:
        raise ValueError('Empty release file')
    return info.st_size


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def archive_check(path, version, commit, platform):
    with zipfile.ZipFile(path) as archive:
        listed = archive.infolist()
        seen = set()
        for item in listed:
            p = PurePosixPath(item.filename)
            if (p.is_absolute() or '\\' in item.filename or ':' in item.filename
                    or any(x in ('', '.', '..') for x in item.filename.split('/'))
                    or item.filename.casefold() in seen or item.is_dir()
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Unsafe release archive entry')
            seen.add(item.filename.casefold())
        prefix = '' if platform == 'windows' else 'jv-cli/'
        if archive.read(prefix + 'VERSION').decode('utf-8').strip() != version:
            raise ValueError('Archive version mismatch')
        if platform == 'windows':
            build = json.loads(archive.read('BUILD.json'))
            if (build['source_commit'] != commit or build['version'] != version
                    or build['engine'] != '0.149.1' or build['architecture'] != 'AMD64'
                    or build['signed'] is not False):
                raise ValueError('Windows build identity mismatch')
            manifest = 'PACKAGE.sha256'
        else:
            manifest = prefix + 'MANIFEST.sha256'
        manifests = [(manifest, prefix)]
        if platform == 'linux' and '-offline.zip' in path.name:
            manifests.append((prefix + 'offline/MANIFEST.sha256', prefix + 'offline/'))
        actual = {item.filename for item in listed}
        checked = set()
        for manifest_name, base in manifests:
            if archive.getinfo(manifest_name).file_size > 4 * 1024 * 1024:
                raise ValueError('Oversized archive manifest')
            checked.add(manifest_name)
            for line in archive.read(manifest_name).decode('utf-8').splitlines():
                digest, relative = line.split('  ', 1)
                name = base + relative
                if not re.fullmatch(r'[0-9a-f]{64}', digest) or name in checked or name not in actual:
                    raise ValueError('Invalid archive manifest')
                checked.add(name)
                h = hashlib.sha256()
                with archive.open(name) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(chunk)
                if h.hexdigest() != digest:
                    raise ValueError('Archive integrity mismatch')
        if actual != checked:
            raise ValueError('Archive inventory mismatch')


def finish(directory, version, commit, platform, builds=None):
    entries = [dict(name=name, bytes=regular(directory / name), sha256=sha(directory / name))
               for name in names(version, platform)]
    meta = dict(version=version, commit=commit, platform=platform, engine='0.149.1',
                bridge_protocol=1, signing='unsigned', reproducible_build_certification=False,
                assets=entries)
    if builds is not None:
        meta['builds'] = builds
    else:
        meta['runner'] = {k: os.environ[k] for k in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion') if k in os.environ}
    write_json(directory / 'BUILD-INFO.json', meta)
    checks = names(version, platform) + ['BUILD-INFO.json']
    (directory / 'SHA256SUMS').write_text(''.join(f'{sha(directory / name)}  {name}\n' for name in checks), encoding='ascii', newline='\n')
    verify(directory, version, commit, platform)


def verify(directory, version, commit, platform):
    identity(version, commit)
    expected = set(names(version, platform) + ['BUILD-INFO.json', 'SHA256SUMS'])
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError('Release inventory mismatch')
    for name in expected:
        regular(directory / name)
    meta = json.loads((directory / 'BUILD-INFO.json').read_text(encoding='utf-8'))
    if (meta.get('version'), meta.get('commit'), meta.get('platform'), meta.get('engine'), meta.get('bridge_protocol'), meta.get('signing')) != (version, commit, platform, '0.149.1', 1, 'unsigned'):
        raise ValueError('Release metadata mismatch')
    expected_assets = names(version, platform)
    if len(meta['assets']) != len(expected_assets) or {e['name'] for e in meta['assets']} != set(expected_assets):
        raise ValueError('Metadata inventory mismatch')
    for item in meta['assets']:
        if regular(directory / item['name']) != item['bytes'] or sha(directory / item['name']) != item['sha256']:
            raise ValueError('Metadata byte mismatch')
    sums = {}
    for line in (directory / 'SHA256SUMS').read_text(encoding='ascii').splitlines():
        digest, name = line.split('  ', 1)
        if name in sums or name not in expected - {'SHA256SUMS'} or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid release checksums')
        sums[name] = digest
    if set(sums) != expected - {'SHA256SUMS'} or any(sha(directory / name) != digest for name, digest in sums.items()):
        raise ValueError('Release checksum mismatch')
    for name in expected_assets:
        if name.endswith('.sha256'):
            target = name[:-7]
            if (directory / name).read_text(encoding='ascii') != f'{sha(directory / target)}  {target}\n':
                raise ValueError('Legacy checksum mismatch')
        elif name.endswith('.zip'):
            archive_check(directory / name, version, commit, 'windows' if '-windows-' in name else 'linux')
    if platform == 'all':
        if set(meta.get('builds', {})) != {'linux', 'windows'}:
            raise ValueError('Missing platform provenance')
        for p, build in meta['builds'].items():
            if (build['version'], build['commit'], build['platform']) != (version, commit, p):
                raise ValueError('Mixed source provenance')
            matching = [e for e in meta['assets'] if e['name'] in names(version, p)]
            if build['assets'] != matching:
                raise ValueError('Platform provenance mismatch')
    print(f'PASS {platform}: {len(expected)} exact release assets, version {version}, commit {commit}', flush=True)
    return meta


def collect(source, output, version, commit, platform):
    identity(version, commit)
    output.mkdir(parents=True, exist_ok=False)
    for name in names(version, platform):
        regular(source / name)
        shutil.copyfile(source / name, output / name)
    finish(output, version, commit, platform)


def assemble(source, output, version, commit):
    builds = {p: verify(source / p, version, commit, p) for p in ('linux', 'windows')}
    output.mkdir(parents=True, exist_ok=False)
    for p in builds:
        for name in names(version, p):
            shutil.copyfile(source / p / name, output / name)
    finish(output, version, commit, 'all', builds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('collect', 'assemble', 'verify'))
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--platform', choices=('linux', 'windows', 'all'), default='all')
    a = parser.parse_args()
    if a.action == 'collect':
        collect(a.source, a.output, a.version, a.commit, a.platform)
    elif a.action == 'assemble':
        assemble(a.source, a.output, a.version, a.commit)
    else:
        verify(a.output, a.version, a.commit, a.platform)


if __name__ == '__main__':
    main()
