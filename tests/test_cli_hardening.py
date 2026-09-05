import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from jvcli import cli
from jvcli.safety import JvError


class CliHardening(unittest.TestCase):
    def engine(self,td,body):
        file=Path(td)/'engine'
        file.write_text('#!/usr/bin/env python3\nimport sys,json,time,os\n'+body)
        file.chmod(0o755)
        return str(file)
    def run_engine(self,body,**kwargs):
        with tempfile.TemporaryDirectory() as td:
            engine=self.engine(td,body)
            with contextlib.redirect_stdout(io.StringIO()) as out,contextlib.redirect_stderr(io.StringIO()) as err:
                result=cli._run_engine(engine,'private prompt',None,**kwargs)
            return result,out.getvalue(),err.getvalue()
    def test_zero_exit_without_final_is_failure(self):
        result,_,err=self.run_engine('print(json.dumps({"type":"turn.completed"}))\n')
        self.assertNotEqual(result[0],0)
        self.assertIn('not reported as success',err)
    def test_turn_failed_even_with_zero_exit_is_failure(self):
        body='print(json.dumps({"type":"turn.failed","error":{"message":"failed"}}),flush=True)\n'
        result,_,_=self.run_engine(body)
        self.assertNotEqual(result[0],0)
    def test_malformed_engine_output_is_failure(self):
        result,_,_=self.run_engine('print("not-json",flush=True)\n')
        self.assertNotEqual(result[0],0)
    def test_timeout_kills_local_engine(self):
        start=time.monotonic()
        result,_,err=self.run_engine('time.sleep(30)\n',turn_timeout=.15)
        self.assertEqual(result[0],124)
        self.assertLess(time.monotonic()-start,4)
        self.assertIn('timed out',err)
    def test_large_prompt_hung_stdin_still_times_out(self):
        with tempfile.TemporaryDirectory() as td:
            engine=self.engine(td,'time.sleep(30)\n')
            start=time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                result=cli._run_engine(engine,'x'*90000,None,turn_timeout=.15)
            self.assertEqual(result[0],124)
            self.assertLess(time.monotonic()-start,4)

    def test_prompt_is_stdin_not_argv(self):
        body='''assert "private prompt" not in sys.argv
assert sys.stdin.read().strip()=="private prompt"
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"ok"}}))
print(json.dumps({"type":"turn.completed"}))
'''
        result,out,_=self.run_engine(body)
        self.assertEqual(result[0],0)
        self.assertEqual(out.strip(),'ok')
    def test_json_mode_stdout_is_only_jsonl(self):
        body='''print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"ok"}}))
print(json.dumps({"type":"turn.completed"}))
'''
        result,out,_=self.run_engine(body,json_mode=True)
        self.assertEqual(result[0],0)
        for line in out.splitlines():self.assertIsInstance(json.loads(line),dict)
    def test_engine_child_does_not_inherit_account_secrets(self):
        with patch.dict(os.environ,{'JV_API_PASSWORD':'SECRET','OPENAI_API_KEY':'SECRET','GITHUB_TOKEN':'SECRET','SSH_AUTH_SOCK':'secret.sock'}):
            env=cli._engine_env()
        self.assertFalse(any(key in env for key in ('JV_API_PASSWORD','OPENAI_API_KEY','GITHUB_TOKEN','SSH_AUTH_SOCK')))
    def test_config_parses_and_enforces_sandbox(self):
        try:import tomllib
        except ImportError:self.skipTest('tomllib available only in Python 3.11+; runtime uses no TOML parser')
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            overrides=cli._write_engine_config(path,12345,read_only=True)
            config=tomllib.loads((path/'engine/config.toml').read_text())
            self.assertEqual(config['sandbox_mode'],'read-only')
            self.assertEqual(config['approval_policy'],'never')
            self.assertFalse(config['sandbox_workspace_write']['network_access'])
            self.assertEqual(config['model_providers']['jv']['env_key'],'JVCLI_ADAPTER_KEY')
            self.assertIn('sandbox_mode="read-only"',overrides)
            self.assertNotIn('danger-full-access',(path/'engine/config.toml').read_text())
    def test_sessions_have_independent_provider_ports(self):
        with tempfile.TemporaryDirectory() as td:
            a,b=Path(td)/'a',Path(td)/'b'
            cli._write_engine_config(a,1234);cli._write_engine_config(b,5678)
            self.assertIn(':1234/v1',(a/'engine/config.toml').read_text())
            self.assertNotIn(':5678/v1',(a/'engine/config.toml').read_text())
    def test_unknown_option_rejected_before_signin(self):
        p=subprocess.run([sys.executable,'-B',str(ROOT/'bin/jvcli'),'exec','--password','bad','hello'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertNotIn('Signed in',p.stderr)
    def test_version_does_not_create_state(self):
        with tempfile.TemporaryDirectory() as td:
            env={**os.environ,'JVCLI_HOME':str(Path(td)/'state')}
            p=subprocess.run([str(ROOT/'jvcli'),'--version'],capture_output=True,text=True,env=env)
            self.assertEqual(p.returncode,0)
            self.assertFalse((Path(td)/'state').exists())
    def test_failed_login_does_not_overwrite_existing_account(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config.json';path.write_text('{"username":"old","base_url":"https://example.com"}')
            with patch.object(cli,'CONFIG_PATH',path),patch.object(cli,'_password',return_value='secret'),patch.object(cli,'_new_client') as constructor:
                constructor.return_value.login.side_effect=JvError('rejected')
                with self.assertRaises(JvError):cli._login_client('new','https://example.com')
            self.assertEqual(json.loads(path.read_text())['username'],'old')
    def test_save_failure_revokes_new_token(self):
        with patch.object(cli,'_resolve_account',return_value=('https://example.com','u')),patch.object(cli,'_password',return_value='secret'),patch.object(cli,'_new_client') as constructor,patch.object(cli,'_save_disk_config',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):cli._login_client()
            constructor.return_value.logout.assert_called_once()
    def test_hidden_password_prompt_refuses_getpass_fallback(self):
        with patch.dict(os.environ,{},clear=True),patch.object(sys.stdin,'isatty',return_value=True),patch.object(cli.getpass,'getpass',side_effect=cli.getpass.GetPassWarning('echo')):
            with self.assertRaises(JvError):cli._password()
    def test_password_environment_removed_from_process(self):
        with patch.dict(os.environ,{'JV_API_PASSWORD':'secret'}):
            self.assertEqual(cli._password(),'secret')
            self.assertNotIn('JV_API_PASSWORD',os.environ)
    def test_unknown_config_fields_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.json';p.write_text('{"password":"secret"}')
            with patch.object(cli,'CONFIG_PATH',p):
                with self.assertRaises(JvError):cli._load_disk_config()
    def test_untrusted_project_config_not_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'.codex').mkdir();(root/'.codex/config.toml').write_text('sandbox_mode="danger-full-access"')
            with self.assertRaises(JvError):cli._workspace_check(root)
    def test_personal_codex_config_is_ignored_and_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)/'home';workspace=home/'projects/example';workspace.mkdir(parents=True)
            config=home/'.codex/config.toml';config.parent.mkdir();config.write_text('personal-setting="keep"\n')
            before=config.read_bytes()
            with patch.object(Path,'home',return_value=home):
                self.assertEqual(cli._workspace_check(workspace),workspace)
            self.assertEqual(config.read_bytes(),before)
    def test_project_ancestor_codex_config_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)/'home';project=home/'projects/example';nested=project/'src';nested.mkdir(parents=True)
            config=project/'.codex/config.toml';config.parent.mkdir();config.write_text('sandbox_mode="danger-full-access"')
            with patch.object(Path,'home',return_value=home):
                with self.assertRaises(JvError):cli._workspace_check(nested)
    def test_engine_home_stays_inside_jv_session(self):
        with tempfile.TemporaryDirectory() as td:
            session=Path(td)/'session';session.mkdir()
            env=cli._engine_env(session,adapter_key='test-key')
            self.assertEqual(env['CODEX_HOME'],str(session/'engine'))
            self.assertNotEqual(Path(env['CODEX_HOME']),Path.home()/'.codex')
    def test_activation_does_not_edit_profiles_and_deactivates(self):
        with tempfile.TemporaryDirectory() as td:
            command='old=$PATH; source "$1/activate.sh" >/dev/null; command -v jvcli; source "$1/activate.sh" >/dev/null; jvcli_deactivate; test "$old" = "$PATH"'
            result=subprocess.run(['bash','-c',command,'test',str(ROOT)],env={**os.environ,'HOME':td},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(list(Path(td).iterdir()),[])
    def test_explicit_bad_engine_never_falls_back_to_global(self):
        with patch.dict(os.environ,{'JVCLI_CODEX_BIN':'/does/not/exist'}):
            with self.assertRaises(JvError):cli._find_engine()
