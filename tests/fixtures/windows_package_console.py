"""Runs in a new hidden console: Ctrl+C targets only this disposable console."""
import ctypes as C
import json
from pathlib import Path
import subprocess
import sys

kernel = C.WinDLL('kernel32', use_last_error=True)
handler_type = C.WINFUNCTYPE(C.c_bool, C.c_ulong)
handler = handler_type(lambda event: True)
kernel.SetConsoleCtrlHandler.argtypes = [handler_type, C.c_bool]
if not kernel.SetConsoleCtrlHandler(handler, True):
    raise C.WinError(C.get_last_error())
with open('CONIN$', 'rb', buffering=0) as ci, open('CONOUT$', 'wb', buffering=0) as co:
    native = subprocess.run([sys.argv[1], '--version'], stdin=ci, stdout=co, stderr=co, timeout=15)
    assert native.returncode == 0, 'Native console handle launch failed'
process = subprocess.Popen([sys.argv[1], 'bridge', '--stdio', '--execution-mode', 'trusted-host'],
                           cwd=sys.argv[2], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    ready = json.loads(process.stdout.readline())
    assert ready['type'] == 'bridge.ready' and ready['protocol'] == 1, ready
    request = {'type': 'unknown', 'request_id': 'console', 'text': '\u0e44\u0e17\u0e22'}
    process.stdin.write((json.dumps(request, ensure_ascii=False)+'\n').encode('utf-8'))
    process.stdin.flush()
    assert json.loads(process.stdout.readline())['request_id'] == request['request_id']
    if not kernel.GenerateConsoleCtrlEvent(0, 0):
        raise C.WinError(C.get_last_error())
    rc = process.wait(15)
    # Shared bridge contract reports signal interruption as exit 2 (normal shutdown is 0).
    assert rc == 2, (rc, process.stderr.read().decode(errors='replace'))
    print('HIDDEN NATIVE CONSOLE / THAI NDJSON / CTRL+C / EXIT CODE: PASS')
finally:
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=5)
