"""Exact pinned Windows grammar differs from the Linux artifact only by CRLF."""
import hashlib
import os
from pathlib import Path
import unittest
import json

from test_structured_core import core_request
from jvcli.structured import StructuredProcessor, PATCH_GRAMMAR_SHA256, WINDOWS_PATCH_GRAMMAR_SHA256
from jvcli.safety import ProtocolError
from jvcli.agent import AgentProcessor


class WindowsGrammar(unittest.TestCase):
    def test_wire_grammar_matches_server_certification(self):
        # central_agent_api.normalize_request at jv-platform
        # 83d7a419e46d7db7c7d2792aefda65f0f925ebaa hashes exact UTF-8
        # declaration bytes, including newlines, before admitting a job.
        request = core_request()
        declaration = next(t for t in request['tools'] if t['name'] == 'apply_patch')
        lf = declaration['format']['definition']
        variants = [lf, lf.replace('\n', '\r\n')] if os.name == 'nt' else [lf]
        for grammar in variants:
            with self.subTest(windows_newlines='\r\n' in grammar):
                declaration['format']['definition'] = grammar
                tools, schemas = AgentProcessor._tools(request)
                wire = json.loads(json.dumps({'tools': tools}).encode('utf-8'))
                patch = next(t for t in wire['tools'] if t['name'] == 'apply_patch')
                self.assertEqual(hashlib.sha256(patch['format']['definition'].encode()).hexdigest(),
                                 PATCH_GRAMMAR_SHA256)
                self.assertEqual(patch['type'], 'custom')
                self.assertEqual(schemas['apply_patch'], {'type': 'custom'})
                self.assertIn('view_image', schemas)
                self.assertEqual(len(tools), 5)
                self.assertEqual(declaration['format']['definition'], grammar)

    def test_uncertified_newlines_are_not_repaired(self):
        request = core_request()
        tool = next(t for t in request['tools'] if t['name'] == 'apply_patch')
        lf = tool['format']['definition']
        for changed in (lf.replace('\n', '\r\n', 1), lf.replace('\n', '\r'), lf + '\n'):
            tool['format']['definition'] = changed
            with self.assertRaises(ProtocolError):
                StructuredProcessor._tools(request)

    def test_exact_platform_grammar(self):
        request = core_request()
        tool = next(t for t in request['tools'] if t['name'] == 'apply_patch')
        lf = tool['format']['definition']
        crlf = lf.replace('\n', '\r\n')
        self.assertEqual(hashlib.sha256(lf.encode()).hexdigest(), PATCH_GRAMMAR_SHA256)
        self.assertEqual(hashlib.sha256(crlf.encode()).hexdigest(), WINDOWS_PATCH_GRAMMAR_SHA256)
        tool['format']['definition'] = crlf
        if os.name == 'nt':
            tools, _ = StructuredProcessor._tools(request)
            forwarded = next(t for t in tools if t['name'] == 'apply_patch')['format']['definition']
            self.assertEqual(forwarded, lf)
            self.assertEqual(hashlib.sha256(forwarded.encode()).hexdigest(), PATCH_GRAMMAR_SHA256)
            self.assertEqual(tool['format']['definition'], crlf, 'Do not mutate engine history')
        else:
            with self.assertRaises(ProtocolError):
                StructuredProcessor._tools(request)
        tool['format']['definition'] += 'altered'
        with self.assertRaises(ProtocolError):
            StructuredProcessor._tools(request)
