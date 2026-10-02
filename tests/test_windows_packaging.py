"""Portable integrity rules shared by the Windows builder and installed gate."""
import hashlib
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_windows import safe_name, verify_payload


class WindowsPackageIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='staging-package-unit-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'file').write_bytes(b'complete')
        self.record = hashlib.sha256(b'complete').hexdigest() + '  file\n'
        (self.root / 'PACKAGE.sha256').write_text(self.record)

    def test_complete_inventory(self):
        self.assertEqual(verify_payload(self.root), 1)

    def test_archive_escape_alias_and_device_names_rejected(self):
        for name in ('/root', '../escape', 'x/../escape', 'C:/file', 'a\\b', 'file:stream',
                     'a//b', './x', 'NUL', 'con.txt', 'a.', 'a ', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_name(name)

    def test_corrupt_file(self):
        (self.root / 'file').write_bytes(b'partial')
        with self.assertRaises(ValueError):
            verify_payload(self.root)

    def test_missing_file(self):
        (self.root / 'file').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            verify_payload(self.root)

    def test_extra_file(self):
        (self.root / 'unexpected').write_bytes(b'not shipped')
        with self.assertRaises(ValueError):
            verify_payload(self.root)

    def test_case_alias_manifest(self):
        (self.root / 'PACKAGE.sha256').write_text(self.record+self.record.replace('file', 'FILE'))
        with self.assertRaises(ValueError):
            verify_payload(self.root)

    def test_hard_link_rejected(self):
        os.link(self.root / 'file', self.root / 'alias')
        with self.assertRaises(ValueError):
            verify_payload(self.root)


if __name__ == '__main__':
    unittest.main()
