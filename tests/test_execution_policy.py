"""Explicit authority selection and unchanged POSIX policy defaults."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from unittest.mock import patch
from jvcli import execution_policy as policy
from jvcli import cli


class ExecutionPolicy(unittest.TestCase):
    def test_linux_defaults_unchanged(self):
        with patch.object(policy.os, 'name', 'posix'):
            self.assertEqual(policy.resolve(), ('workspace-write', True))
            self.assertEqual(policy.resolve(read_only=True), ('read-only', False))
            self.assertEqual(policy.resolve(allow_network=False), ('workspace-write', False))
            with self.assertRaises(policy.UnsupportedCapability):
                policy.resolve('trusted-host')

    def test_windows_secure_denial_fails_closed(self):
        with patch.object(policy.os, 'name', 'nt'):
            for args in ({'allow_network': False}, {'read_only': True}):
                with self.assertRaisesRegex(policy.UnsupportedCapability, 'cannot guarantee network isolation'):
                    policy.resolve(**args)
            self.assertEqual(policy.resolve(), ('workspace-write', True))

    def test_trusted_host_explicit_and_conflicts_rejected(self):
        with patch.object(policy.os, 'name', 'nt'):
            self.assertEqual(policy.resolve('trusted-host'), ('danger-full-access', True))
            for args in ({'allow_network': False}, {'read_only': True}):
                with self.assertRaises(policy.UnsupportedCapability):
                    policy.resolve('trusted-host', **args)

    def test_parser_selection_before_or_after_command(self):
        for argv in (['--execution-mode', 'trusted-host', 'bridge', '--stdio'],
                     ['bridge', '--stdio', '--execution-mode', 'trusted-host'],
                     ['exec', '--execution-mode', 'trusted-host', 'synthetic']):
            self.assertEqual(cli._parser().parse_args(argv).execution_mode, 'trusted-host')
        self.assertIsNone(cli._parser().parse_args(['bridge', '--stdio']).execution_mode)
