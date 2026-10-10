"""Native Windows real-engine vision transport acceptance; synthetic loopback only.

Requires existing Node, Playwright Chromium and Pillow. Use --launcher to repeat
against an extracted/installed candidate. Never discovers account/session state.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

import windows_preflight
from windows_test_support import trusted_fixture_directory
from jvcli.platform import windows
from vision_bridge_smoke import Fixture, Peer, PASSWORD, TOKEN

ROOT = windows_preflight.ROOT


class WindowsPeer(Peer):
    def __init__(self, folder, workspace, url, engine, python, launcher=None):
        self.frames = []
        self.lines = queue.Queue(maxsize=1024)
        env = windows.minimal_env()
        env.update(PROCESSOR_ARCHITECTURE='AMD64', USERPROFILE=str(Path.home()),
                   JVCLI_HOME=str(folder/'state'), JVCLI_AGENT_API='0', JVCLI_POLL_INTERVAL='0.01')
        prefix = [str(launcher)] if launcher else [str(python), '-s', '-B', str(ROOT/'bin/jvcli')]
        if not launcher:
            env.update(PYTHONHOME=sys.base_prefix, JVCLI_CODEX_BIN=str(engine))
        self.p = subprocess.Popen(prefix+['bridge','--stdio','--execution-mode','trusted-host'],
            cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.stderr = bytearray()

        def read_lines():
            try:
                while True:
                    line = self.p.stdout.readline(128*1024+1)
                    self.lines.put(line, timeout=5)
                    if not line or len(line)>128*1024:
                        return
            except (OSError, ValueError, queue.Full):
                return

        def read_errors():
            while True:
                chunk = self.p.stderr.read(4096)
                if not chunk:
                    return
                self.stderr.extend(chunk[:max(0, 65536-len(self.stderr))])

        self.reader = threading.Thread(target=read_lines, daemon=True)
        self.errors_reader = threading.Thread(target=read_errors, daemon=True)
        self.reader.start(); self.errors_reader.start()
        try:
            ready = self.read()
            assert ready.get('capabilities',{}).get('tool_images') is True, ready
            self.send('auth.login', username='synthetic',base_url=url,password=PASSWORD)
            assert self.read()['type']=='auth.succeeded'
        except BaseException:
            self.close()
            raise

    def read(self, timeout=120):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError('Native bridge timeout') from None
        assert line, 'Native bridge exited'
        assert len(line)<=128*1024 and line.endswith(b'\n'), 'Unbounded bridge frame'
        assert not any(value.encode() in line for value in (PASSWORD,TOKEN,'base64,','image_url'))
        frame=json.loads(line)
        self.frames.append(frame)
        return frame

    def close(self):
        try:
            if self.p.poll() is None:
                self.send('bridge.shutdown')
                while self.read()['type'] != 'bridge.stopping':
                    pass
                self.p.wait(timeout=20)
            assert self.p.returncode==0
        finally:
            if self.p.poll() is None:
                self.p.kill(); self.p.wait(timeout=10)
            self.reader.join(5); self.errors_reader.join(5)
            for pipe in (self.p.stdin,self.p.stdout,self.p.stderr):
                pipe.close()
            assert not any(value.encode() in self.stderr for value in (PASSWORD,TOKEN,'base64,','image_url'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('engine','node','playwright','browsers'):
        parser.add_argument('--'+option,type=Path,required=True)
    parser.add_argument('--launcher',type=Path)
    parser.add_argument('--desktop-probe',type=Path)
    args=parser.parse_args()
    if os.name!='nt':
        parser.error('Native Windows required')
    if args.desktop_probe and not args.launcher:
        parser.error('--desktop-probe requires --launcher for the native executable')
    engine=windows.find_engine(ROOT/'runtime',str(args.engine.resolve(strict=True)))
    with tempfile.TemporaryDirectory(prefix='staging-vision-',dir=ROOT) as temporary:
        folder=Path(temporary)
        trusted_fixture_directory(folder)
        workspace=folder/'workspace'; workspace.mkdir()
        for name in ('python.exe',f'python{sys.version_info.major}{sys.version_info.minor}.dll','python3.dll'):
            source=Path(sys.executable).parent/name
            if source.exists(): shutil.copyfile(source,folder/name)
        fixture=Fixture(workspace,args.node.resolve(),args.playwright.resolve(),args.browsers.resolve())
        peer=None
        def start(location):
            location.mkdir(exist_ok=True)
            return WindowsPeer(location,workspace,fixture.url,engine,folder/'python.exe',args.launcher)
        try:
            if args.desktop_probe:
                subprocess.run([str(args.desktop_probe.resolve(strict=True)),str(args.launcher.resolve(strict=True)),
                    str(workspace),str(folder/'desktop-state'),fixture.url],check=True,timeout=240)
            else:
                peer=start(folder/'structured')
                peer.send('session.start',transport='structured',read_only=False,allow_network=True)
                session=peer.read(); assert session['transport']=='structured',session
                assert peer.turn()['type']=='turn.completed',peer.frames[-1]
                peer.close(); peer=None
                peer=start(folder/'structured')
                peer.send('session.start',transport='structured',resume_session_id=session['session_id'],read_only=False,allow_network=True)
                resumed=peer.read(); assert resumed['session_id']==session['session_id'] and resumed['thread_id']
                assert peer.turn()['type']=='turn.completed',peer.frames[-1]
                peer.close(); peer=None
            assert not fixture.errors,fixture.errors
            assert len(fixture.images)==3 and fixture.completed_tasks==2
            assert fixture.legacy_posts==0
            assert 'After inspection' in (workspace/'dist/index.html').read_text()
            fixture.mode='unsupported'
            peer=start(folder/'unsupported')
            peer.send('session.start',transport='structured',read_only=False,allow_network=True)
            assert peer.read()['type']=='session.started'
            before=fixture.posts
            failure=peer.turn()
            assert failure['type']=='turn.failed' and failure['support_code']=='JV-AGENT-UNSUPPORTED-001',failure
            assert fixture.posts==before+1 and peer.p.poll() is None and fixture.legacy_posts==0
            peer.close(); peer=None
            fixture.mode='legacy'
            peer=start(folder/'legacy')
            peer.send('session.start',transport='legacy',read_only=False,allow_network=True)
            assert peer.read()['transport']=='legacy'
            assert peer.turn()['type']=='turn.completed'
            assert fixture.legacy_posts==1 and not fixture.errors
            peer.close(); peer=None
            print(json.dumps({'ok':True,'live_inference':False,'native_platform':'win32',
                'images':len(fixture.images),'completed_tasks':fixture.completed_tasks,
                'bridge_restart_resume':not bool(args.desktop_probe),'desktop_supervisor':bool(args.desktop_probe),
                'unsupported_single_submission':True,
                'explicit_fresh_legacy_session':True,'launcher':bool(args.launcher)},indent=2))
        finally:
            if peer: peer.close()
            fixture.close()


if __name__=='__main__':
    main()
