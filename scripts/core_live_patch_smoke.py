#!/usr/bin/env python3
"""One bounded live custom apply_patch acceptance, with hidden credentials."""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts'))
from jvcli import cli
from jvcli.safety import JvError, atomic_write, private_dir, redact
from jvcli.transport import JvApiClient, JvClientConfig
from core_live_smoke import calls, execute, response_text, result_for


def main():
    if os.geteuid() == 0 or not sys.stdin.isatty():
        raise JvError('A normal-user terminal is required')
    root = private_dir(cli.STATE_DIR / 'live-patch' / secrets.token_hex(4))
    report_path = root / 'report.json'
    report = {'status': 'awaiting_hidden_login', 'engine': '0.149.1',
              'contract': '52be8980e01828959df7712ddae17d077d69efcf'}
    atomic_write(report_path, json.dumps(report, indent=2) + '\n')
    print('One bounded production apply_patch scenario; no automatic retry.')
    username = input('JV LLM username: ').strip()
    os.environ.pop('JV_API_PASSWORD', None)
    client = JvApiClient(JvClientConfig(base_url='https://ai.openjvspace.com',
        request_timeout=30, wait_timeout=300, poll_interval=3,
        temp_dir=private_dir(root / 'tmp')))
    try:
        password = cli._password()
        try:
            client.login(username, password)
        finally:
            del password
        workspace = private_dir(root / 'workspace')
        session = private_dir(root / 'session')
        marker = 'LOCAL_PATCH_' + secrets.token_hex(5)
        rounds = execute(client, cli._find_engine(), session, workspace,
            'Use the custom apply_patch tool to create proof.txt containing exactly '
            + marker + ' followed by a newline. Then use shell_command to cat proof.txt '
            'and report that exact observed token. Do not create the file through shell.',
            max_rounds=5)
        patches = calls(rounds, 'apply_patch')
        shells = calls(rounds, 'shell_command')
        if (not patches or not shells or (workspace / 'proof.txt').read_text() != marker + '\n'
                or marker not in response_text(rounds)
                or any(result_for(rounds, call)['type'] != 'custom_tool_call_output'
                       for call in patches)):
            raise JvError('Live custom patch evidence was incomplete')
        report = {'status': 'passed', 'engine': '0.149.1',
                  'contract': report['contract'], 'rounds': len(rounds),
                  'response_ids': [item['response_id'] for item in rounds],
                  'tool_names': [item['output']['name'] for item in rounds
                                 if item.get('output', {}).get('name')],
                  'prompt_repairs': 0, 'local_file_verified': True}
        atomic_write(report_path, json.dumps(report, indent=2) + '\n')
        print('Live custom apply_patch: PASS')
        return 0
    except (JvError, OSError, KeyboardInterrupt, StopIteration, ValueError) as exc:
        report['status'] = 'failed'
        report['error'] = redact(str(exc), (client._token or '',))[:500]
        atomic_write(report_path, json.dumps(report, indent=2) + '\n')
        print('Live custom apply_patch stopped; no automatic retry.')
        return 1
    finally:
        cli._logout(client)


if __name__ == '__main__':
    raise SystemExit(main())
