#!/usr/bin/env python3
"""Pinned-engine network boundary investigation; synthetic loopback only.

Returns nonzero if a deny case connects. Captures only TCP owner PID, process
name/parent PID and membership of the JV-owned job. Never changes network policy.
"""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from engine_smoke import run_case
from jvcli.platform import windows


def connection_owner(family, local_port, remote_port):
    from ctypes import wintypes as W
    api = C.WinDLL('iphlpapi').GetExtendedTcpTable
    api.argtypes = [C.c_void_p, C.POINTER(W.DWORD), W.BOOL, W.ULONG, C.c_int, W.ULONG]
    api.restype = W.DWORD
    size = W.DWORD()
    api(None, C.byref(size), False, family, 5, 0)
    data = C.create_string_buffer(size.value)
    if api(data, C.byref(size), False, family, 5, 0):
        raise OSError('TCP ownership query failed')
    count = W.DWORD.from_buffer(data).value
    stride, lp, rp, pid = (24, 8, 16, 20) if family == socket.AF_INET else (56, 20, 44, 52)
    for index in range(count):
        base = 4 + index * stride
        if (socket.ntohs(W.DWORD.from_buffer(data, base + lp).value & 65535) == local_port
                and socket.ntohs(W.DWORD.from_buffer(data, base + rp).value & 65535) == remote_port):
            return W.DWORD.from_buffer(data, base + pid).value
    raise OSError('No matching client TCP owner')


def probe(engine, root, family, tool, executable, allowed, execution_mode=None):
    from jvcli.platform import _windows_fs as fs
    listener = socket.socket(family)
    address = '127.0.0.1' if family == socket.AF_INET else '::1'
    listener.bind((address, 0)); listener.listen(); listener.settimeout(8)
    port = listener.getsockname()[1]
    processes, evidence, errors = [], [], []
    original = windows.spawn_engine
    def spawn(command, env):
        process = original(command, env)
        processes.append(process)
        return process
    def accept():
        try:
            conn, peer = listener.accept()
            with conn:
                pid = connection_owner(family, peer[1], port)
                open_process = fs._api(fs.K, 'OpenProcess', fs.W.HANDLE, fs.D, fs.W.BOOL, fs.D)
                in_job = fs._api(fs.K, 'IsProcessInJob', fs.W.BOOL, fs.W.HANDLE, fs.W.HANDLE, C.POINTER(fs.W.BOOL))
                handle = fs._check(open_process(0x1000, False, pid))
                owned = fs.W.BOOL()
                try:
                    with processes[-1]._mutex:
                        fs._check(in_job(handle, processes[-1]._job, C.byref(owned)))
                finally:
                    fs._close(handle)
                ps = str(Path(windows.minimal_env()['SYSTEMROOT']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
                query = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; $q=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p.ParentProcessId); @($p,$q) | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress"
                result = subprocess.run([ps, '-NoProfile', '-Command', query], capture_output=True,
                                        text=True, timeout=6, shell=False, env=windows.minimal_env())
                if result.returncode:
                    raise OSError('Process identity query failed')
                evidence.append({'tcp_owner_pid': pid, 'owned_job': bool(owned.value),
                                 'processes': json.loads(result.stdout)})
                conn.sendall(b'x')
        except socket.timeout:
            pass
        except Exception as exc:
            errors.append(type(exc).__name__)
    thread = threading.Thread(target=accept)
    thread.start()
    if tool == 'powershell':
        af = 'InterNetwork' if family == socket.AF_INET else 'InterNetworkV6'
        command = f"$c=New-Object System.Net.Sockets.TcpClient -ArgumentList ([System.Net.Sockets.AddressFamily]::{af}); $c.Connect('{address}',{port}); $null=$c.GetStream().ReadByte(); $c.Close(); Write-Output 'CONNECTED'"
    elif tool == 'python':
        code = f"import socket; s=socket.socket({int(family)}); s.connect(('{address}',{port})); s.recv(1); s.close(); print('CONNECTED')"
        command = "& '" + executable.replace("'", "''") + "' -B -c '" + code.replace("'", "''") + "'"
    else:
        code = f"const n=require('net');const s=n.connect({{host:'{address}',port:{port}}});s.on('data',()=>{{s.end();console.log('CONNECTED')}});"
        command = "& '" + executable.replace("'", "''") + "' -e '" + code.replace("'", "''") + "'"
    state = windows.private_dir(root / f'{family}-{tool}-{allowed}')
    try:
        with patch.object(windows, 'spawn_engine', spawn):
            run_case(engine, state, 'synthetic network boundary', [
                ({'type': 'tool_call', 'name': 'shell_command', 'arguments': {'command': command}}, None),
                ({'type': 'final', 'text': 'DONE'}, None)], allow_network=allowed, execution_mode=execution_mode)
    finally:
        thread.join(9)
        listener.close()
    if errors or thread.is_alive():
        raise RuntimeError('Network ownership evidence incomplete')
    connected = bool(evidence)
    print(json.dumps({'family': 'IPv4' if family == socket.AF_INET else 'IPv6', 'tool': tool,
                      'allow_network': allowed, 'connected': connected, 'evidence': evidence}))
    return connected == allowed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--execution-mode', choices=['trusted-host'])
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Native Windows required')
    engine = windows.find_engine(ROOT / 'runtime', args.engine)
    tools = [('powershell', None), ('python', sys.executable)]
    node = shutil.which('node')
    if node:
        tools.append(('node', node))
    else:
        raise SystemExit('Node unavailable: network matrix incomplete')
    original = Path.cwd()
    passed = True
    with tempfile.TemporaryDirectory(prefix='staging-network-', dir=ROOT) as temp:
        root = Path(temp); workspace = root / 'workspace'; workspace.mkdir()
        os.chdir(workspace)
        try:
            for family in (socket.AF_INET, socket.AF_INET6):
                for tool, executable in tools:
                    for allowed in ((True,) if args.execution_mode else (False, True)):
                        passed &= probe(engine, root, family, tool, executable, allowed, args.execution_mode)
        finally:
            os.chdir(original)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
