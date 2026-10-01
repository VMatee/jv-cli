#!/usr/bin/env python3
"""Synthetic engine: no API client or network. Only private test state is written."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if sys.argv[1:] == ['--version']:
    print('codex-cli 0.149.1')
    raise SystemExit(0)
stdin_raw = sys.stdin.read()
prompt = stdin_raw.rstrip('\n')
root = Path(os.environ['CODEX_HOME']).parent
(root / 'fixture-capture.json').write_text(json.dumps({
    'argv': sys.argv, 'stdin': prompt, 'stdin_raw': stdin_raw, 'env': dict(os.environ), 'pid': os.getpid(),
}), encoding='utf-8')

def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

emit({'type': 'thread.started', 'thread_id': '--dangerously-bypass-approvals-and-sandbox' if prompt == 'option-thread' else 'thread_fixture'})
emit({'type': 'turn.started'})
if prompt == 'tree':
    child = subprocess.Popen([sys.executable, '-B', '-c', 'import time;time.sleep(60)'])
    (root / 'fixture-child.pid').write_text(str(child.pid))
if prompt in ('slow', 'tree'):
    time.sleep(60)
if prompt == 'crash':
    print('TEST_TOKEN_DO_NOT_LEAK TEST_ADAPTER_KEY_DO_NOT_LEAK', file=sys.stderr)
    raise SystemExit(7)
if prompt == 'malformed':
    print('{bad', flush=True)
    raise SystemExit(0)
if prompt == 'oversized':
    print('x' * (1024 * 1024 + 1), flush=True)
    raise SystemExit(0)
if prompt == 'failed':
    emit({'type': 'turn.failed', 'error': {'message': 'TEST_TOKEN_DO_NOT_LEAK'}})
    raise SystemExit(0)
if prompt == 'flood':
    for i in range(10000):
        emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'x' * 32000}})
emit({'type': 'new.unknown', 'password': 'TEST_TOKEN_DO_NOT_LEAK'})
emit({'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'synthetic check'}})
emit({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'synthetic check',
      'exit_code': 0, 'aggregated_output': 'TEST_TOKEN_DO_NOT_LEAK TEST_ADAPTER_KEY_DO_NOT_LEAK'}})
emit({'type': 'item.started', 'item': {'type': 'mcp_tool_call', 'tool': 'synthetic-tool'}})
emit({'type': 'item.completed', 'item': {'type': 'file_change', 'changes': [{'path': 'example.txt', 'kind': 'update'}]}})
emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'เรียบร้อยแล้ว'}})
emit({'type': 'turn.completed'})
