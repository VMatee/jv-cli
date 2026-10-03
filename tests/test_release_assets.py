import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_assets as r


class ReleaseAssets(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version, self.commit = '0.5.0', 'a' * 40
        self.source = self.root / 'source'
        self.source.mkdir()
        for platform in ('linux', 'windows'):
            for name in r.names(self.version, platform):
                target = self.source / name
                if name.endswith('.sha256'):
                    target.write_text(f'{r.sha(self.source / name[:-7])}  {name[:-7]}\n', encoding='ascii', newline='\n')
                elif name.endswith('.zip'):
                    prefix = '' if platform == 'windows' else 'jv-cli/'
                    contents = {prefix + 'VERSION': b'0.5.0\n'}
                    manifest = prefix + 'MANIFEST.sha256'
                    if platform == 'windows':
                        contents['BUILD.json'] = json.dumps(dict(version=self.version, source_commit=self.commit, engine='0.149.1', architecture='AMD64', signed=False)).encode()
                        manifest = 'PACKAGE.sha256'
                    data = ''.join(f'{hashlib.sha256(value).hexdigest()}  {key[len(prefix):]}\n' for key, value in contents.items()).encode()
                    contents[manifest] = data
                    if '-offline.zip' in name:
                        contents[prefix + 'offline/MANIFEST.sha256'] = b''
                    with zipfile.ZipFile(target, 'w') as z:
                        for key, value in contents.items():
                            z.writestr(key, value)
                else:
                    target.write_bytes(b'Synthetic unsigned installer')

    def collect(self, platform):
        target = self.root / 'parts' / platform
        r.collect(self.source, target, self.version, self.commit, platform)
        return target

    def test_two_platform_roundtrip_and_legacy_hashes(self):
        for platform in ('linux', 'windows'):
            self.collect(platform)
        r.assemble(self.root / 'parts', self.root / 'release', self.version, self.commit)
        meta = r.verify(self.root / 'release', self.version, self.commit, 'all')
        self.assertEqual(len(meta['assets']), 6)

    def test_changed_installer_is_rejected(self):
        target = self.collect('windows')
        (target / r.names(self.version, 'windows')[1]).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            r.verify(target, self.version, self.commit, 'windows')

    def test_missing_or_extra_asset_is_rejected(self):
        target = self.collect('windows')
        (target / 'unlisted.txt').write_text('unexpected')
        with self.assertRaises(ValueError):
            r.verify(target, self.version, self.commit, 'windows')
        (target / 'unlisted.txt').unlink()
        (target / 'SHA256SUMS').unlink()
        with self.assertRaises(ValueError):
            r.verify(target, self.version, self.commit, 'windows')

    def test_mixed_commit_is_rejected(self):
        self.collect('linux')
        target = self.collect('windows')
        meta = json.loads((target / 'BUILD-INFO.json').read_text())
        meta['commit'] = 'b' * 40
        r.write_json(target / 'BUILD-INFO.json', meta)
        with self.assertRaises(ValueError):
            r.assemble(self.root / 'parts', self.root / 'release', self.version, self.commit)

    def test_archive_version_is_rejected(self):
        with self.assertRaises(ValueError):
            r.archive_check(self.source / r.names(self.version, 'windows')[0], '0.5.1', self.commit, 'windows')

    def test_archive_escape_is_rejected(self):
        path = self.source / r.names(self.version, 'windows')[0]
        with zipfile.ZipFile(path, 'a') as z:
            z.writestr('../outside', b'bad')
        with self.assertRaises(ValueError):
            r.archive_check(path, self.version, self.commit, 'windows')

    def test_partial_archive_is_rejected(self):
        path = self.source / r.names(self.version, 'linux')[0]
        with zipfile.ZipFile(path, 'a') as z:
            z.writestr('jv-cli/unlisted', b'bad')
        with self.assertRaises(ValueError):
            r.archive_check(path, self.version, self.commit, 'linux')

    def test_duplicate_checksum_is_rejected(self):
        target = self.collect('windows')
        path = target / 'SHA256SUMS'
        path.write_text(path.read_text() * 2)
        with self.assertRaises(ValueError):
            r.verify(target, self.version, self.commit, 'windows')

    def test_metadata_size_and_duplicate_inventory_are_rejected(self):
        target = self.collect('windows')
        path = target / 'BUILD-INFO.json'
        meta = json.loads(path.read_text())
        meta['assets'][0]['bytes'] += 1
        r.write_json(path, meta)
        with self.assertRaises(ValueError):
            r.verify(target, self.version, self.commit, 'windows')

        meta['assets'][0]['bytes'] -= 1
        meta['assets'].append(dict(meta['assets'][0]))
        r.write_json(path, meta)
        with self.assertRaises(ValueError):
            r.verify(target, self.version, self.commit, 'windows')

    def test_invalid_identity_is_rejected(self):
        for v, c in (('../bad', self.commit), (self.version, 'bad')):
            with self.assertRaises(ValueError):
                r.identity(v, c)


if __name__ == '__main__':
    unittest.main()
