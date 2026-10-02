#!/usr/bin/env python3
"""Offline Windows trusted-host bridge gate; missing invariants are fatal.

Uses only synthetic responses and a loopback listener. No accounts/inference API.
Final installation and release packaging are deliberately outside this gate.
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

import windows_preflight
from engine_smoke import run_case, run_structured_case
from jvcli.platform import windows

ROOT = Path(__file__).resolve().parents[1]


def engine_checks(engine):
    results = {}
    engine = windows.find_engine(ROOT / 'runtime', engine)
    old = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='staging-bridge-engine-', dir=ROOT) as temp:
        root = Path(temp)
        workspace = root / 'workspace'
        workspace.mkdir()
        outside = root / 'outside.txt'
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(.2)
        os.chdir(workspace)
        try:
            # All commands below are fixed synthetic model tool instructions,
            # never user prompt transport. The runner sends its prompt on stdin.
            cases = [
                ('workspace_write', "Set-Content -LiteralPath 'allowed.txt' -Value 'SYNTHETIC'; Write-Output 'WRITE_OK'", False, 'WRITE_OK'),
                ('outside_denied', "try { Set-Content -LiteralPath '" + str(outside).replace("'", "''") + "' -Value 'SYNTHETIC' -ErrorAction Stop; Write-Output 'ESCAPE' } catch { Write-Output 'DENIED' }", False, 'DENIED'),
                ('readonly_denied', "try { Set-Content -LiteralPath 'readonly.txt' -Value 'SYNTHETIC' -ErrorAction Stop; Write-Output 'ESCAPE' } catch { Write-Output 'DENIED' }", True, 'DENIED'),
                ('tool_secret_exclusion', "if ($env:JVCLI_ADAPTER_KEY -or $env:JV_API_PASSWORD -or $env:OPENAI_API_KEY) { Write-Output 'LEAK' } else { Write-Output 'ISOLATED' }", False, 'ISOLATED'),
                ('network_denied', "try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect('127.0.0.1'," + str(listener.getsockname()[1]) + "); $c.Close(); Write-Output 'NETWORK_ALLOWED' } catch { Write-Output 'NETWORK_DENIED' }", False, 'NETWORK_DENIED'),
            ]
            for name, command, readonly, marker in cases:
                state = windows.private_dir(root / name)
                try:
                    run_case(engine, state, name, [
                        ({'type': 'tool_call', 'name': 'shell_command', 'arguments': {'command': command}}, None),
                        ({'type': 'final', 'text': 'OK'}, marker)], read_only=readonly, allow_network=False)
                    results[name] = True
                except Exception:
                    results[name] = False
            results['workspace_write'] &= (workspace / 'allowed.txt').is_file()
            results['outside_denied'] &= not outside.exists()
            results['readonly_denied'] &= not (workspace / 'readonly.txt').exists()
            try:
                connection, _ = listener.accept()
                connection.close()
                results['network_denied'] = False
            except socket.timeout:
                pass
            try:
                state = windows.private_dir(root / 'structured-journal')
                run_structured_case(engine, state, "Write-Output 'STRUCTURED_NATIVE_OK'", 'STRUCTURED_NATIVE_OK')
                results['structured_journal'] = True
            except Exception:
                results['structured_journal'] = False
        finally:
            os.chdir(old)
            listener.close()
    for name, passed in results.items():
        print(f'Pinned engine {name}: {"PASS" if passed else "FAIL"}')
    return all(results.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--restricted-investigation', action='store_true', help='Historical restricted sandbox gate; expected unsupported/failure')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Native Windows required')
    passed = True
    for category, names in (
        ('shared', windows_preflight.SHARED_TESTS),
        ('filesystem/ACL', ('test_windows_native',)),
        ('execution/process', ('test_windows_execution',)),
        ('pipes/dispatch', ('test_windows_pipes',)),
        ('auth deadlines', ('test_windows_auth',)),
        ('pinned grammar', ('test_windows_grammar',)),
        ('journal durability', ('test_windows_journal',)),
        ('execution policy', ('test_execution_policy',)),
    ):
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
        ok = result.wasSuccessful() and not result.skipped
        print(f'{category}: {result.testsRun} tests; {"PASS" if ok else "FAIL"}')
        passed &= ok
    if args.restricted_investigation:
        return 0 if engine_checks(args.engine) and passed else 1
    from windows_trusted_acceptance import run
    passed &= run(args.engine)
    probe = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/windows_network_probe.py'),
                            '--engine', args.engine, '--execution-mode', 'trusted-host'],
                           cwd=ROOT, shell=False, timeout=180)
    passed &= probe.returncode == 0
    print('Secure Windows network-denied execution: UNSUPPORTED by pinned restricted-token backend; requests fail closed')
    print('TRUSTED-HOST WINDOWS ACCEPTANCE: ' + ('PASS' if passed else 'FAIL'))
    return 0 if passed else 1



if __name__ == '__main__':
    raise SystemExit(main())
