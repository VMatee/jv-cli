import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('jv_manage',ROOT/'scripts/manage.py')
manage=importlib.util.module_from_spec(spec);spec.loader.exec_module(manage)
from jvcli.safety import JvError


class InstallationTests(unittest.TestCase):
    def source(self,p):
        (p/'lib/jvcli').mkdir(parents=True)
        (p/'lib/jvcli/cli.py').write_text('new-code')
        (p/'VERSION').write_text('new-version')
        entries=[]
        for name in ('lib/jvcli/cli.py','VERSION'):
            entries.append(hashlib.sha256((p/name).read_bytes()).hexdigest()+'  '+name)
        (p/'MANIFEST.sha256').write_text('\n'.join(entries)+'\n')
    def test_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.source(root)
            self.assertEqual(len(manage.manifest(root)),2)
            (root/'VERSION').write_text('tampered')
            with self.assertRaises(JvError):manage.manifest(root)
    def test_upgrade_preserves_state_runtime_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'new';source.mkdir();self.source(source)
            dest=Path(td)/'old';(dest/'lib/jvcli').mkdir(parents=True)
            (dest/'lib/jvcli/cli.py').write_text('old-code')
            (dest/'.state').mkdir();(dest/'.state/config.json').write_text('{"username":"keep"}')
            (dest/'runtime').mkdir();(dest/'runtime/keep').write_text('engine')
            with contextlib.redirect_stdout(io.StringIO()):manage.upgrade(source,dest)
            self.assertEqual((dest/'lib/jvcli/cli.py').read_text(),'new-code')
            self.assertEqual((dest/'runtime/keep').read_text(),'engine')
            self.assertEqual(json.loads((dest/'.state/config.json').read_text())['username'],'keep')
            backups=list((dest/'.backups').glob('*/lib/jvcli/cli.py'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(),'old-code')
    def test_upgrade_refuses_symlink_destination(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'new';source.mkdir();self.source(source)
            dest=Path(td)/'old';(dest/'lib/jvcli').mkdir(parents=True)
            original=Path(td)/'original';original.write_text('keep')
            (dest/'lib/jvcli/cli.py').symlink_to(original)
            with self.assertRaises(JvError):manage.upgrade(source,dest)
            self.assertEqual(original.read_text(),'keep')
    def test_upgrade_rolls_back_if_a_later_copy_fails(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'new';source.mkdir();self.source(source)
            dest=Path(td)/'old';(dest/'lib/jvcli').mkdir(parents=True)
            (dest/'lib/jvcli/cli.py').write_text('old-code')
            (dest/'VERSION').mkdir() # triggers failure after cli.py has been copied
            with self.assertRaises(JvError):manage.upgrade(source,dest)
            self.assertEqual((dest/'lib/jvcli/cli.py').read_text(),'old-code')
    def test_root_install_refused(self):
        with patch.object(os,'geteuid',return_value=0):
            with self.assertRaises(JvError):manage.install(ROOT,no_engine=True)
    def test_no_engine_install_stays_inside_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'jv-cli';root.mkdir();(root/'bin').mkdir()
            (root/'jvcli').write_text('launcher');(root/'bin/jvcli').write_text('launcher')
            home=Path(td)/'home';home.mkdir()
            with patch.object(os,'geteuid',return_value=1000),patch.dict(os.environ,{'HOME':str(home)}),contextlib.redirect_stdout(io.StringIO()):
                manage.install(root,no_engine=True,portable=True)
            self.assertEqual(list(home.iterdir()),[])
            self.assertTrue((root/'.state').is_dir())
    def test_failed_engine_install_preserves_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'jv';root.mkdir();(root/'runtime').mkdir();(root/'runtime/keep').write_text('old-engine')
            def fake_run(command,**kwargs):
                import subprocess
                if command[0]=='node':return subprocess.CompletedProcess(command,0,'22.0.0\n','')
                return subprocess.CompletedProcess(command,1)
            with patch.object(os,'geteuid',return_value=1000),patch.object(manage.shutil,'which',return_value='/fake'),patch.object(manage.subprocess,'run',side_effect=fake_run),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(JvError):manage.install(root)
            self.assertEqual((root/'runtime/keep').read_text(),'old-engine')
    def test_active_session_blocks_upgrade(self):
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'.state/runs/session').mkdir(parents=True)
            with (root/'.state/runs/session/session.lock').open('w') as file:
                fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(JvError):manage.idle(root)
