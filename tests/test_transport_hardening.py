import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from jvcli.transport import JvApiClient,JvClientConfig,HttpError,NetworkError
from jvcli.safety import JvError,SubmissionUncertain,Cancelled
from jvcli.adapter import AdapterRuntime


class Server:
    def __init__(self):
        self.events=[];self.mode='ok';self.polls=0;self.posts=0;self.logout_status=204
        self.answer='{"type":"final","text":"done"}'
        self.file_data=b'hello';self.manifest_size=5;self.file_status=200
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status=200,payload=None,headers=None,body=None):
                raw=body if body is not None else json.dumps(payload or {}).encode()
                self.send_response(status)
                for k,v in (headers or {}).items():self.send_header(k,v)
                if status!=204:self.send_header('Content-Length',str(len(raw)))
                self.end_headers()
                if status!=204:
                    try:self.wfile.write(raw)
                    except (BrokenPipeError,ConnectionResetError):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
                owner.events.append((self.path,dict(self.headers),raw))
                if self.path=='/v1/auth/login':
                    if owner.mode=='bad_login':return self.reply(401,{'error':{'message':'password=SECRET'}})
                    if owner.mode=='redirect_login':return self.reply(302,headers={'Location':owner.base+'/stolen'})
                    if owner.mode=='bad_token':return self.reply(payload={'access_token':'bad\nheader'})
                    return self.reply(payload={'access_token':'TEST-TOKEN'})
                if self.path=='/v1/auth/logout':return self.reply(owner.logout_status)
                if self.path=='/v1/jobs':
                    owner.posts+=1
                    if owner.mode=='post_500':return self.reply(500)
                    if owner.mode=='post_429':return self.reply(429,headers={'Retry-After':'5'})
                    if owner.mode=='post_bad_json':return self.reply(202,body=b'{')
                    if owner.mode=='post_bad_id':return self.reply(202,{'id':'../bad','conversation_id':'conv_1','status':'queued'})
                    if owner.mode=='post_disconnect':
                        self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                    return self.reply(202,owner.job('queued'))
                return self.reply(404)
            def do_GET(self):
                owner.events.append((self.path,dict(self.headers),b''))
                if '/response-files/' in self.path:
                    if owner.file_status==302:return self.reply(302,headers={'Location':owner.base+'/stolen'})
                    return self.reply(owner.file_status,body=owner.file_data)
                if self.path=='/v1/jobs/job_1':
                    owner.polls+=1
                    if owner.mode=='get_bad_json':return self.reply(body=b'{')
                    if owner.mode=='get_bad_id':return self.reply(payload={'id':'job_2','conversation_id':'conv_1','status':'succeeded'})
                    if owner.mode=='get_401':return self.reply(401)
                    if owner.mode=='get_429':return self.reply(429,headers={'Retry-After':'3'})
                    if owner.mode=='get_retry' and owner.polls==1:return self.reply(503,headers={'Retry-After':'0'})
                    if owner.mode=='get_running':return self.reply(payload=owner.job('running'))
                    if owner.mode=='get_slow':time.sleep(.3)
                    return self.reply(payload=owner.job('succeeded'))
                return self.reply(404)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http.daemon_threads=True
        self.base=f'http://127.0.0.1:{self.http.server_address[1]}'
        self.thread=threading.Thread(target=lambda:self.http.serve_forever(poll_interval=.01),daemon=True)
        self.thread.start()
    def job(self,status):
        return {'id':'job_1','conversation_id':'conv_1','status':status,'answer':self.answer,'response':{'files':[]}}
    def client(self,**options):
        return JvApiClient(JvClientConfig(base_url=self.base,poll_interval=.01,request_timeout=.1,wait_timeout=options.pop('wait_timeout',.4),**options))
    def close(self):self.http.shutdown();self.http.server_close();self.thread.join(1)


class TransportHardening(unittest.TestCase):
    def setUp(self):
        self.server=Server();self.client=self.server.client();self.client.login('user','pass')
    def tearDown(self):
        with contextlib.suppress(JvError):self.client.logout()
        self.server.close()
    def test_login_request_exact_and_no_remember(self):
        path,headers,body=self.server.events[0]
        self.assertEqual(path,'/v1/auth/login')
        self.assertEqual(json.loads(body),{'username':'user','password':'pass','remember_me':False})
        self.assertNotIn('Authorization',headers)
    def test_bad_credentials_error_does_not_echo_server_body(self):
        self.client.logout();self.server.mode='bad_login'
        with self.assertRaises(HttpError) as cm:self.client.login('user','pass')
        self.assertNotIn('SECRET',str(cm.exception))
    def test_login_redirect_not_followed(self):
        self.client.logout();self.server.mode='redirect_login'
        with self.assertRaises(JvError):self.client.login('user','pass')
        self.assertFalse(any(p=='/stolen' for p,_,_ in self.server.events))
    def test_invalid_token_rejected(self):
        self.client.logout();self.server.mode='bad_token'
        with self.assertRaises(JvError):self.client.login('user','pass')
        self.assertFalse(self.client.authenticated)
    def test_logout_clears_token_even_if_revocation_fails(self):
        self.server.logout_status=500
        with self.assertRaises(JvError):self.client.logout()
        self.assertFalse(self.client.authenticated)
    def test_submit_multipart_and_conversation(self):
        self.client.submit_job('hello',conversation_id='conv_1')
        path,headers,raw=self.server.events[-1]
        self.assertEqual(headers.get('Authorization'),'Bearer TEST-TOKEN')
        self.assertEqual(headers.get('X-Jv-Csrf'),'1')
        self.assertIn(b'name="text"',raw);self.assertIn(b'name="conversation_id"',raw)
        self.assertIn(b'conv_1',raw)
    def test_uncertain_500_never_retried(self):
        self.server.mode='post_500'
        with self.assertRaises(SubmissionUncertain):self.client.submit_job('hello')
        self.assertEqual(self.server.posts,1)
    def test_uncertain_202_malformed_never_retried(self):
        self.server.mode='post_bad_json'
        with self.assertRaises(SubmissionUncertain):self.client.submit_job('hello')
        self.assertEqual(self.server.posts,1)
    def test_uncertain_202_invalid_id_never_retried(self):
        self.server.mode='post_bad_id'
        with self.assertRaises(SubmissionUncertain):self.client.submit_job('hello')
        self.assertEqual(self.server.posts,1)
    def test_uncertain_disconnect_never_retried(self):
        self.server.mode='post_disconnect'
        with self.assertRaises(SubmissionUncertain):self.client.submit_job('hello')
        self.assertEqual(self.server.posts,1)
    def test_definite_429_never_resubmitted(self):
        self.server.mode='post_429'
        with self.assertRaises(HttpError) as cm:self.client.submit_job('hello')
        self.assertEqual(cm.exception.retry_after,5)
        self.assertEqual(self.server.posts,1)
    def test_transient_get_retried(self):
        self.server.mode='get_retry'
        self.assertEqual(self.client.wait_for_job('job_1')['status'],'succeeded')
        self.assertEqual(self.server.polls,2)
    def test_malformed_get_not_retried(self):
        self.server.mode='get_bad_json'
        with self.assertRaises(JvError):self.client.wait_for_job('job_1')
        self.assertEqual(self.server.polls,1)
    def test_mismatched_job_not_retried(self):
        self.server.mode='get_bad_id'
        with self.assertRaises(JvError):self.client.wait_for_job('job_1')
        self.assertEqual(self.server.polls,1)
    def test_401_not_retried(self):
        self.server.mode='get_401'
        with self.assertRaises(HttpError):self.client.wait_for_job('job_1')
        self.assertEqual(self.server.polls,1)
    def test_retry_after_not_shortened_to_deadline(self):
        self.server.mode='get_429'
        self.client.config.wait_timeout=.06
        with self.assertRaises(JvError):self.client.wait_for_job('job_1')
        self.assertEqual(self.server.polls,1)
    def test_poll_wait_timeout(self):
        self.server.mode='get_running';self.client.config.wait_timeout=.035
        with self.assertRaises(JvError) as cm:self.client.wait_for_job('job_1')
        self.assertIn('not cancelled',str(cm.exception))
    def test_slow_get_bounded_by_remaining_wait(self):
        self.server.mode='get_slow';self.client.config.wait_timeout=.04
        start=time.monotonic()
        with self.assertRaises(JvError):self.client.wait_for_job('job_1')
        self.assertLess(time.monotonic()-start,.2)
    def test_pre_cancelled_poll_does_not_send_request(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):self.client.wait_for_job('job_1',cancel=cancel)
        self.assertEqual(self.server.polls,0)
    def test_submit_conversation_consistency(self):
        with self.assertRaises(SubmissionUncertain):self.client.submit_job('hello',conversation_id='conv_other')
    def test_poll_conversation_consistency(self):
        with self.assertRaises(JvError):self.client.wait_for_job('job_1',conversation_id='conv_other')
        self.assertEqual(self.server.polls,1)
    def test_oversized_json_response_rejected(self):
        with patch('jvcli.transport.MAX_JSON_BYTES',5):
            with self.assertRaises(JvError):self.client._read_json(io.BytesIO(b'{"large":true}'))
    def test_bad_status_type_is_controlled_error(self):
        for status in ([],None,'unknown'):
            job=self.server.job('succeeded');job['status']=status
            with self.assertRaises(JvError):self.client._validate_job(job)
    def test_upload_real_multipart_contents(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sample.txt';p.write_text('ATTACHED CONTENT')
            self.client.submit_job('read file',file_paths=[p])
            raw=self.server.events[-1][2]
            self.assertIn(b'name="files"; filename="sample.txt"',raw)
            self.assertIn(b'ATTACHED CONTENT',raw)
    def test_upload_symlink_rejected_before_post(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a';p.write_text('data');link=Path(td)/'b';link.symlink_to(p)
            with self.assertRaises(JvError):self.client.submit_job('read file',file_paths=[link])
            self.assertEqual(self.server.posts,0)
    def test_upload_size_limit_before_post(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a';p.write_text('12345')
            with patch('jvcli.transport.MAX_FILE_BYTES',3):
                with self.assertRaises(JvError):self.client.submit_job('read',file_paths=[p])
            self.assertEqual(self.server.posts,0)
    def file_job(self,url=None,size=5,name='report.txt'):
        job=self.server.job('succeeded');job['response']['files']=[{'url':url or '/v1/jobs/job_1/response-files/file_1','size_bytes':size,'name':name}]
        return job
    def test_download_exact_size_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            result=self.client.download_response_files(self.file_job(),Path(td)/'downloads')
            self.assertEqual(result[0].read_bytes(),b'hello')
            self.assertEqual(result[0].stat().st_mode&0o777,0o600)
    def test_download_collision_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'report.txt';p.write_text('keep')
            files=self.client.download_response_files(self.file_job(),Path(td))
            self.assertEqual(p.read_text(),'keep')
            self.assertNotEqual(files[0],p)
    def test_existing_download_directory_permissions_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);p.chmod(0o755)
            self.client.download_response_files(self.file_job(),p)
            self.assertEqual(p.stat().st_mode&0o777,0o755)
    def test_cross_origin_and_path_traversal_downloads_rejected(self):
        bad=('https://evil.example/file','/v1/jobs/other/response-files/file_1',
             '/v1/jobs/job_1/response-files/../secret','/v1/jobs/job_1/response-files/%2e%2e',
             '/v1/jobs/job_1/response-files/file_1?x=1')
        with tempfile.TemporaryDirectory() as td:
            for url in bad:
                with self.subTest(url=url):
                    with self.assertRaises(JvError):self.client.download_response_files(self.file_job(url),Path(td))
    def test_unsafe_name_cannot_escape_directory(self):
        with tempfile.TemporaryDirectory() as td:
            files=self.client.download_response_files(self.file_job(name='../../outside'),Path(td)/'out')
            self.assertEqual(files[0].parent,Path(td)/'out')
            self.assertFalse((Path(td)/'outside').exists())
    def test_symlink_destination_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            real=Path(td)/'real';real.mkdir();link=Path(td)/'link';link.symlink_to(real)
            with self.assertRaises(JvError):self.client.download_response_files(self.file_job(),link)
    def test_download_size_mismatch_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(JvError):self.client.download_response_files(self.file_job(size=6),Path(td))
            self.assertEqual(list(Path(td).iterdir()),[])
    def test_download_redirect_rejected(self):
        self.server.file_status=302
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(JvError):self.client.download_response_files(self.file_job(),Path(td))
        self.assertFalse(any(p=='/stolen' for p,_,_ in self.server.events))
    def test_download_boolean_size_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(JvError):self.client.download_response_files(self.file_job(size=True),Path(td))


class AdapterHardening(unittest.TestCase):
    def setUp(self):
        self.server=Server();self.client=self.server.client(wait_timeout=1);self.client.login('user','pass')
        self.runtime=AdapterRuntime(self.client,heartbeat=.02);self.port=self.runtime.start()
        self.payload={'model':'jv-local','input':[{'role':'user','content':'hello'}],'tools':[],'stream':True}
    def tearDown(self):
        self.runtime.close();self.client.logout();self.server.close()
    def request(self,payload=None,headers=None,raw=None):
        hdr={'Content-Type':'application/json','Authorization':'Bearer '+self.runtime.key}
        hdr.update(headers or {})
        data=json.dumps(payload or self.payload).encode() if raw is None else raw
        return urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/responses',data=data,headers=hdr,method='POST')
    def test_missing_adapter_token_cannot_submit_job(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.request(headers={'Authorization':''}))
        self.assertEqual(cm.exception.code,401);cm.exception.close();self.assertEqual(self.server.posts,0)
    def test_browser_origin_blocked_even_with_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.request(headers={'Origin':'https://evil.example'}))
        self.assertEqual(cm.exception.code,403);cm.exception.close();self.assertEqual(self.server.posts,0)
    def test_invalid_host_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.request(headers={'Host':'evil.example'}))
        self.assertEqual(cm.exception.code,403);cm.exception.close()
    def test_non_json_content_type_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.request(headers={'Content-Type':'text/plain'}))
        self.assertEqual(cm.exception.code,415);cm.exception.close()
    def test_malformed_body_does_not_submit(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(self.request(raw=b'{'))
        self.assertEqual(cm.exception.code,400);cm.exception.close();self.assertEqual(self.server.posts,0)
    def test_unknown_model_rejected(self):
        payload={**self.payload,'model':'wrong'}
        with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(self.request(payload))
        self.assertEqual(cm.exception.code,400);cm.exception.close()
    def test_nonstream_response_valid(self):
        with urllib.request.urlopen(self.request({**self.payload,'stream':False})) as response:data=json.load(response)
        self.assertEqual(data['status'],'completed');self.assertEqual(data['output'][0]['content'][0]['text'],'done')
        self.assertNotIn('usage',data)
    def test_stream_events_complete_and_ordered(self):
        with urllib.request.urlopen(self.request()) as response:text=response.read().decode()
        events=[json.loads(line[6:]) for line in text.splitlines() if line.startswith('data: ') and line!='data: [DONE]']
        self.assertEqual(events[0]['type'],'response.created')
        self.assertEqual(events[-1]['type'],'response.completed')
        self.assertEqual([e['sequence_number'] for e in events],list(range(len(events))))
    def test_stream_heartbeat_while_polling(self):
        self.server.mode='get_running';self.client.config.wait_timeout=.09
        with urllib.request.urlopen(self.request()) as response:text=response.read().decode()
        self.assertIn(': jv-keepalive',text)
        self.assertIn('response.failed',text)
        self.assertNotIn('response.completed',text)
    def test_stream_error_explicit_not_false_success(self):
        self.server.answer='{"type":"tool_call","name":"not_offered","arguments":{}}'
        with urllib.request.urlopen(self.request()) as response:text=response.read().decode()
        self.assertIn('response.failed',text);self.assertNotIn('response.completed',text)
    def test_busy_adapter_does_not_submit_twice(self):
        self.runtime.lock.acquire()
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(self.request())
            self.assertEqual(cm.exception.code,409);cm.exception.close()
            self.assertEqual(self.server.posts,0)
        finally:self.runtime.lock.release()
    def test_request_limit_stops_new_job(self):
        self.runtime.max_requests=1
        with urllib.request.urlopen(self.request()) as response:response.read()
        with urllib.request.urlopen(self.request()) as response:text=response.read().decode()
        self.assertIn('limit reached',text);self.assertEqual(self.server.posts,1)
