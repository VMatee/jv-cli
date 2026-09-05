import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import manage
from jvcli import cli
from jvcli.safety import JvError

spec = importlib.util.spec_from_file_location("jv_build_release", ROOT / "scripts/build_release.py")
build_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_release)


class PublicReleaseTests(unittest.TestCase):
    def install_without_engine(self, home):
        with patch.object(os, "geteuid", return_value=1000), contextlib.redirect_stdout(io.StringIO()):
            manage.install(ROOT, no_engine=True, home=home)
        return home / ".local/share/jv-cli"

    def test_normal_user_install_and_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            installed = self.install_without_engine(home)
            launcher = home / ".local/bin/jvcli"
            self.assertTrue(launcher.is_symlink())
            self.assertEqual(launcher.resolve(), installed / "bin/jvcli")
            result = subprocess.run([str(launcher), "--version"], env={**os.environ, "HOME": str(home)},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn((ROOT / "VERSION").read_text().strip(), result.stdout)

    def test_doctor_works_after_installed_engine_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            installed = self.install_without_engine(home)
            engine = installed / "runtime/node_modules/.bin/codex"
            engine.parent.mkdir(parents=True)
            engine.write_text("#!/bin/sh\ncase \"$1\" in --version) echo 'codex-cli 0.149.1';; *) echo --json;; esac\n")
            engine.chmod(0o755)
            result = subprocess.run([str(home / ".local/bin/jvcli"), "doctor"],
                                    env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_portable_install_does_not_create_local_home_paths(self):
        with tempfile.TemporaryDirectory() as td:
            temporary = Path(td)
            source = temporary / "source"
            shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", ".state", ".cache", "runtime", ".backups", "dist", "__pycache__"))
            manage.write_manifest(source)
            home = temporary / "home"
            home.mkdir()
            with patch.object(os, "geteuid", return_value=1000), contextlib.redirect_stdout(io.StringIO()):
                manage.install(source, no_engine=True, portable=True, home=home)
            self.assertFalse((home / ".local").exists())
            self.assertTrue((source / ".state").is_dir())

    def test_uninstall_removes_only_owned_paths(self):
        with tempfile.TemporaryDirectory() as td:
            temporary = Path(td)
            home = temporary / "home"
            home.mkdir()
            project = temporary / "project"
            project.mkdir()
            marker = project / "keep.txt"
            marker.write_text("keep")
            installed = self.install_without_engine(home)
            with contextlib.redirect_stdout(io.StringIO()):
                manage.uninstall(home, yes=True)
            self.assertFalse(installed.exists())
            self.assertFalse((home / ".local/bin/jvcli").exists())
            self.assertEqual(marker.read_text(), "keep")

    def test_uninstall_refuses_unexpected_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            root = home / ".local/share/jv-cli"
            (root / "lib/jvcli").mkdir(parents=True)
            (root / "lib/jvcli/cli.py").write_text("keep")
            (root / "VERSION").write_text("0")
            victim = Path(td) / "victim"
            victim.write_text("keep")
            launcher = home / ".local/bin/jvcli"
            launcher.parent.mkdir(parents=True)
            launcher.symlink_to(victim)
            with self.assertRaises(JvError):
                manage.uninstall(home, yes=True)
            self.assertEqual(victim.read_text(), "keep")
            self.assertTrue(root.exists())

    def test_keep_state_uninstall_preserves_state_only(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            installed = self.install_without_engine(home)
            (installed / ".state/config.json").write_text('{"username":"keep"}')
            with contextlib.redirect_stdout(io.StringIO()):
                manage.uninstall(home, keep_state=True, yes=True)
            self.assertEqual((installed / ".state/config.json").read_text(), '{"username":"keep"}')
            self.assertFalse((installed / "lib").exists())
            with patch.object(os, "geteuid", return_value=1000), contextlib.redirect_stdout(io.StringIO()):
                manage.install(ROOT, no_engine=True, home=home)
            self.assertEqual((installed / ".state/config.json").read_text(), '{"username":"keep"}')
            self.assertTrue((installed / "lib/jvcli/cli.py").is_file())

    def test_path_addition_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            with patch.dict(os.environ, {"PATH": "/usr/bin"}), contextlib.redirect_stdout(io.StringIO()):
                manage._path_notice(home, True)
                manage._path_notice(home, True)
            self.assertEqual((home / ".bashrc").read_text().count(manage.PATH_LINE), 1)

    def test_version_file_is_canonical(self):
        self.assertEqual(cli.VERSION, (ROOT / "VERSION").read_text().strip())
        self.assertNotRegex((ROOT / "lib/jvcli/cli.py").read_text(), r"(?m)^VERSION\s*=\s*['\"]\d")

    def test_release_archive_name_checksum_and_exclusions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "source"
            (root / "scripts").mkdir(parents=True)
            (root / "VERSION").write_text("1.2.3\n")
            (root / "install.sh").write_text("#!/bin/sh\n")
            (root / ".state").mkdir()
            (root / ".state/secret").write_text("secret")
            (root / "runtime/node_modules").mkdir(parents=True)
            (root / "runtime/node_modules/private").write_text("private")
            (root / ".env.local").write_text("SECRET=value")
            with patch.object(build_release, "ROOT", root):
                build_release.main()
            archive = root / "dist/jv-cli-1.2.3-linux-x86_64.zip"
            checksum = archive.with_suffix(".zip.sha256")
            self.assertTrue(archive.is_file())
            self.assertEqual(checksum.read_text().split()[0], hashlib.sha256(archive.read_bytes()).hexdigest())
            with zipfile.ZipFile(archive) as value:
                names = value.namelist()
            self.assertIn("jv-cli/install.sh", names)
            self.assertFalse(any(part in name for name in names for part in (".state/", "runtime/", ".env")))

    def test_release_build_needs_no_credentials(self):
        text = (ROOT / "scripts/build_release.py").read_text()
        self.assertNotIn("JV_API_PASSWORD", text)
        self.assertNotIn("GITHUB_TOKEN", text)

    def test_bootstrap_rejects_bad_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "release.zip"
            checksum = Path(td) / "release.zip.sha256"
            archive.write_bytes(b"archive")
            checksum.write_text("0" * 64 + "  release.zip\n")
            result = subprocess.run(["sh", str(ROOT / "scripts/install-from-github.sh"), "--verify-only",
                                     str(archive), str(checksum)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Checksum verification failed", result.stderr)

    def test_manifest_rejects_generated_private_files(self):
        names = {path.as_posix() for path in manage.public_files(ROOT)}
        self.assertFalse(any(name.startswith((".state/", ".cache/", "runtime/", ".backups/", "dist/")) for name in names))
        self.assertFalse(any("__pycache__/" in name or name.endswith((".pyc", ".pyo")) for name in names))


if __name__ == "__main__":
    unittest.main()
