import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_gate as gate


class ReleaseGate(unittest.TestCase):
    def setUp(self):
        self.version = (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
        self.commit = 'a' * 40
        self.env = dict(GITHUB_REF='refs/tags/v' + self.version,
                        GITHUB_REF_NAME='v' + self.version, GITHUB_SHA=self.commit,
                        GITHUB_REPOSITORY='synthetic/repo')
        self.runs = [dict(name=name, head_branch='main', event='push', status='completed', conclusion='success')
                     for name in ('JV CLI regression tests', 'JV CLI release')]

    def api(self, route):
        if route.endswith('/branches/main'):
            return dict(commit=dict(sha=self.commit))
        if '/actions/runs?' in route:
            return dict(workflow_runs=self.runs)
        raise HTTPError('https://example.invalid', 404, 'absent', {}, None)

    def run_gate(self, api=None):
        with patch.dict(os.environ, self.env), patch.object(gate, 'api', api or self.api):
            gate.main()

    def test_rehearsal_never_uses_publication_api(self):
        self.env['GITHUB_REF'] = 'refs/heads/main'
        with patch.dict(os.environ, self.env), patch.object(gate, 'api') as api:
            gate.main()
            api.assert_not_called()

    def test_exact_green_main_and_absent_release_allowed(self):
        self.run_gate()

    def test_tag_version_mismatch_rejected(self):
        self.env['GITHUB_REF_NAME'] = 'v0.0.0'
        with self.assertRaises(RuntimeError):
            self.run_gate()

    def test_nonmain_source_rejected(self):
        self.env['GITHUB_SHA'] = 'b' * 40
        with self.assertRaises(RuntimeError):
            self.run_gate()

    def test_red_or_missing_main_gate_rejected(self):
        self.runs[1]['conclusion'] = 'failure'
        with self.assertRaises(RuntimeError):
            self.run_gate()
        self.runs.pop()
        with self.assertRaises(RuntimeError):
            self.run_gate()

    def test_existing_release_never_replaced(self):
        def existing(route):
            return {} if '/releases/tags/' in route else self.api(route)
        with self.assertRaises(RuntimeError):
            self.run_gate(existing)

    def test_api_denial_not_assumed_to_be_absent(self):
        def denied(route):
            if '/releases/tags/' in route:
                raise HTTPError('https://example.invalid', 403, 'denied', {}, None)
            return self.api(route)
        with self.assertRaises(RuntimeError):
            self.run_gate(denied)
