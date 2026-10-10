#!/usr/bin/env python3
"""Opt-in Linux bridge/engine/browser acceptance with loopback scripted inference.

No production endpoints or credentials. The fixture sees validated image bytes,
not a vision model. Private engine history may contain images by design; reports
and bridge/UI events must not. Requires existing Playwright, Chromium and Pillow.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from jvcli.images import validate_image_results

PASSWORD = 'SYNTHETIC_VISION_PASSWORD'
TOKEN = 'SYNTHETIC_VISION_TOKEN'


def shell_python(code):
    return shlex.join([sys.executable, '-B', '-c', code])


class Fixture:
    def __init__(self, workspace, node, playwright, browsers, mode='success'):
        self.workspace = workspace
        self.mode = mode
        self.posts = self.legacy_posts = 0
        self.images = []
        self.errors = []
        self.steps = []
        html = '<!doctype html><title>Vision fixture</title><h1>Before inspection</h1><p>Local synthetic site</p>'
        files = {'index.html': html, 'package.json': json.dumps({'private': True, 'scripts': {
            'build': 'node build.cjs', 'test': 'node test.cjs'}}),
            'build.cjs': "const fs=require('node:fs'); fs.mkdirSync('dist',{recursive:true}); fs.copyFileSync('index.html','dist/index.html'); console.log('BUILD_OK');",
            'test.cjs': "const assert=require('node:assert/strict'),fs=require('node:fs'); assert.match(fs.readFileSync('dist/index.html','utf8'), /<h1>.+<\\/h1>/); console.log('TEST_OK');"}
        create = shell_python('from pathlib import Path; files='+repr(files)+'; [(Path(k).write_text(v)) for k,v in files.items()]')
        build_test = shlex.join([str(node), 'build.cjs'])+' && '+shlex.join([str(node), 'test.cjs'])
        capture = (
            "const {chromium}=require("+json.dumps(str(playwright))+ ");"
            "const fs=require('node:fs'); (async()=>{const b=await chromium.launch();try{"
            "const p=await b.newPage({viewport:{width:640,height:360}});"
            "await p.route('**/*',r=>r.abort());await p.setContent(fs.readFileSync('dist/index.html','utf8'));"
            "await p.screenshot({path:'screen.png'}); await p.screenshot({path:'screen.jpg',type:'jpeg'});"
            "console.log('SCREENSHOTS_OK');}finally{await b.close();}})().catch(()=>process.exit(1));"
        )
        capture_command = 'PLAYWRIGHT_BROWSERS_PATH='+shlex.quote(str(browsers))+' '+shlex.join([str(node), '-e', capture])
        webp = shell_python("from PIL import Image; Image.open('screen.png').save('screen.webp'); print('WEBP_OK')")
        modify = shell_python("from pathlib import Path; p=Path('index.html'); p.write_text(p.read_text().replace('Before inspection','After inspection')); print('EDIT_OK')")
        verify = shell_python("from pathlib import Path; assert 'After inspection' in Path('dist/index.html').read_text(); print('FINAL_TEST_OK')")
        self.steps = [
            ('shell_command', {'command':create+' && '+build_test}, 'TEST_OK'),
            ('shell_command', {'command':capture_command+' && '+webp}, 'WEBP_OK'),
            *[('view_image', {'path':'screen.'+ext}, 'image') for ext in ('png','jpg','webp')],
            ('shell_command', {'command':modify+' && '+build_test+' && '+verify}, 'FINAL_TEST_OK'),
        ]
        self.step = 0
        self.awaiting = None
        self.completed_tasks = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                try:
                    if self.path == '/v1/jobs':
                        assert self.headers.get('Authorization') == 'Bearer '+TOKEN
                        owner.legacy_posts += 1
                        size = int(self.headers.get('Content-Length','0'))
                        assert size <= 256*1024
                        self.rfile.read(size)
                        if owner.mode == 'legacy':
                            return self.reply(202, {'id':'job_legacy','conversation_id':'job_legacy','status':'queued'})
                        return self.reply(400, {'error':{'code':'JV-TEST-001','message':'Unexpected legacy submission'}})
                    size = int(self.headers.get('Content-Length', '0'))
                    assert size <= 17 * 1024 * 1024
                    body = json.loads(self.rfile.read(size)) if size else {}
                    if self.path == '/v1/auth/login':
                        assert body['username'] == 'synthetic' and body['password'] == PASSWORD
                        return self.reply(200, {'access_token':TOKEN})
                    assert self.headers.get('Authorization') == 'Bearer '+TOKEN
                    if self.path == '/v1/auth/logout':
                        return self.reply(200, {})
                    assert self.path == '/v1/responses'
                    owner.posts += 1
                    if owner.mode == 'unsupported':
                        return self.reply(404, {'error':{'code':'JV-AGENT-UNSUPPORTED-001','message':'Synthetic unsupported capability'}})
                    return self.reply(200, owner.response(body))
                except Exception as exc:
                    owner.errors.append(type(exc).__name__)
                    self.reply(400, {'error':{'code':'JV-TEST-001','message':'Synthetic assertion failed'}})

            def do_GET(self):
                assert owner.mode == 'legacy' and self.path == '/v1/jobs/job_legacy'
                assert self.headers.get('Authorization') == 'Bearer '+TOKEN
                self.reply(200, {'id':'job_legacy','conversation_id':'job_legacy','status':'succeeded',
                    'answer':json.dumps({'type':'final','text':'LEGACY_EXPLICIT_OK'}),
                    'result_ready':True,'response':{'files':[]}})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)

    def response(self, body):
        assert body['stream'] is False and body['parallel_tool_calls'] is False
        assert any(t.get('name') == 'view_image' for t in body['tools'])
        ctx = json.loads(body['instructions'].split('JV task context (data):\n')[-1])
        if self.awaiting:
            output = body['input'][0]['output']
            assert body.get('previous_response_id')
            if self.awaiting == 'image':
                validate_image_results(output)
                from PIL import Image
                import io
                for part in output:
                    data = base64.b64decode(part['image_url'].split(',',1)[1], validate=True)
                    with Image.open(io.BytesIO(data)) as img:
                        assert img.size == (640,360)
                        img.load()
                    self.images.append({'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            else:
                assert self.awaiting in output
            self.awaiting = None
        n = self.posts
        if ctx['completion_review']:
            text = json.dumps({'protocol':'jv-task-completion-v2','task_id':ctx['task_id'],
                'checkpoint':ctx['checkpoint'],'original_request':'Reviewed synthetic task.',
                'evidence':'Fixture validated actual screenshot bytes; no real model inference.',
                'actions':'Tool results confirm build, screenshot capture and subsequent edit.',
                'artifacts':'dist/index.html passed final tests.','unresolved':[],
                'plan_resolutions':[],'final_answer':'VISION_BRIDGE_OK'})
            self.completed_tasks += 1
            item = self.message(text,n)
        elif self.step < len(self.steps):
            name,args,self.awaiting = self.steps[self.step]
            self.step += 1
            item = {'type':'function_call','id':f'item_{n}','call_id':f'call_{n}',
                'status':'completed','name':name,'arguments':json.dumps(args)}
        elif self.completed_tasks == 1 and not ctx['completed_actions']:
            self.awaiting = 'RESUME_OK'
            item = {'type':'function_call','id':f'item_{n}','call_id':f'call_{n}',
                'status':'completed','name':'shell_command','arguments':json.dumps({'command':shell_python(
                "from pathlib import Path; assert 'After inspection' in Path('index.html').read_text(); print('RESUME_OK')")})}
        else:
            item = self.message('Ready for the mandatory completion review.',n)
        return {'id':f'response_{n}','object':'response','status':'completed','error':None,'output':[item]}

    @staticmethod
    def message(text,n):
        return {'type':'message','id':f'item_{n}','status':'completed','role':'assistant',
            'content':[{'type':'output_text','text':text,'annotations':[]}]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class Peer:
    def __init__(self, folder, workspace, url):
        env = {**os.environ,'JVCLI_HOME':str(folder/'state'),'HOME':str(folder/'home'),
            'JVCLI_AGENT_API':'0','PYTHONDONTWRITEBYTECODE':'1'}
        (folder/'home').mkdir(exist_ok=True)
        self.p = subprocess.Popen([str(ROOT/'bin/jvcli'),'bridge','--stdio'],cwd=workspace,
            env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.pending = b''
        self.frames = []
        ready = self.read()
        if ready.get('capabilities',{}).get('tool_images') is not True:
            self.p.stdin.close(); self.p.wait(timeout=20)
            self.p.stdout.close(); self.p.stderr.close()
            raise AssertionError(('Bridge not ready', ready))
        self.send('auth.login',username='synthetic',base_url=url,password=PASSWORD)
        assert self.read()['type'] == 'auth.succeeded'

    def send(self, typ, **fields):
        self.p.stdin.write((json.dumps({'type':typ,'request_id':uuid.uuid4().hex,**fields})+'\n').encode())
        self.p.stdin.flush()

    def read(self, timeout=120):
        end = time.monotonic()+timeout
        while b'\n' not in self.pending:
            assert time.monotonic() < end and select.select([self.p.stdout],[],[],max(0,end-time.monotonic()))[0], 'Bridge timeout'
            chunk = os.read(self.p.stdout.fileno(),65536)
            assert chunk, 'Bridge exited'
            self.pending += chunk
        line,self.pending = self.pending.split(b'\n',1)
        assert len(line) <= 128*1024
        assert not any(secret.encode() in line for secret in (PASSWORD,TOKEN,'base64,','image_url'))
        frame = json.loads(line)
        self.frames.append(frame)
        return frame

    def turn(self):
        self.send('turn.start',text='Build the synthetic website, inspect screenshots, edit and verify it.')
        while True:
            frame = self.read()
            if frame['type'] in ('turn.failed','turn.completed','turn.cancelled'):
                return frame

    def close(self):
        try:
            if self.p.poll() is None:
                self.send('bridge.shutdown')
                assert self.read()['type'] == 'bridge.stopping'
                self.p.wait(timeout=20)
            assert self.p.returncode == 0
            assert self.p.stderr.read() == b''
        finally:
            if self.p.poll() is None:
                self.p.kill(); self.p.wait()
            for pipe in (self.p.stdin,self.p.stdout,self.p.stderr): pipe.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node',type=Path,required=True)
    parser.add_argument('--playwright',type=Path,required=True)
    parser.add_argument('--browsers',type=Path,required=True)
    parser.add_argument('--desktop-probe',type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux': parser.error('Linux acceptance only')
    # Outside developer-home ancestry: project config is deliberately rejected
    # by the production workspace guard, and we never bypass that guard.
    folder=Path(tempfile.mkdtemp(prefix='jv-vision-bridge-'))
    workspace=folder/'workspace'; workspace.mkdir()
    fixture=Fixture(workspace,args.node.resolve(),args.playwright.resolve(),args.browsers.resolve())
    peer=None
    try:
        if args.desktop_probe:
            subprocess.run([str(args.desktop_probe.resolve()),str(ROOT/'bin/jvcli'),str(workspace),
                str(folder/'desktop-state'),fixture.url],check=True,timeout=240)
        else:
            peer=Peer(folder,workspace,fixture.url)
            peer.send('session.start',transport='structured',read_only=False,allow_network=True)
            session=peer.read(); assert session['transport']=='structured'
            assert peer.turn()['type']=='turn.completed', peer.frames[-1]
            peer.close(); peer=None
            # Restart the bridge and resume the exact private session/thread.
            peer=Peer(folder,workspace,fixture.url)
            peer.send('session.start',transport='structured',resume_session_id=session['session_id'],read_only=False,allow_network=True)
            resumed=peer.read(); assert resumed['session_id']==session['session_id'] and resumed['thread_id']
            assert peer.turn()['type']=='turn.completed', peer.frames[-1]
            peer.close(); peer=None
        assert not fixture.errors,fixture.errors
        assert len(fixture.images)==3 and fixture.completed_tasks==2
        assert fixture.legacy_posts==0
        assert 'After inspection' in (workspace/'dist/index.html').read_text()
        fixture.mode='unsupported'
        error_folder=folder/'unsupported'; error_folder.mkdir()
        peer=Peer(error_folder,workspace,fixture.url)
        peer.send('session.start',transport='structured',read_only=False,allow_network=True)
        assert peer.read()['type']=='session.started'
        failure=peer.turn()
        assert failure['type']=='turn.failed' and failure['support_code']=='JV-AGENT-UNSUPPORTED-001',failure
        assert peer.p.poll() is None and fixture.legacy_posts==0
        peer.close();peer=None
        fixture.mode='legacy'
        legacy_folder=folder/'legacy';legacy_folder.mkdir()
        peer=Peer(legacy_folder,workspace,fixture.url)
        peer.send('session.start',transport='legacy',read_only=False,allow_network=True)
        assert peer.read()['transport']=='legacy'
        assert peer.turn()['type']=='turn.completed'
        assert fixture.legacy_posts==1
        peer.close();peer=None
        report={'ok':True,'live_inference':False,'native_platform':'linux','images':len(fixture.images),
            'completed_tasks':fixture.completed_tasks,'unsupported_no_fallback':True,'bridge_stayed_alive':True,
            'explicit_fresh_legacy_session':True,
            'desktop_supervisor':bool(args.desktop_probe),'bridge_restart_resume':not bool(args.desktop_probe),
            'fixture':str(folder)}
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        if peer: peer.close()
        fixture.close()


if __name__=='__main__': main()
