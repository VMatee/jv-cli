"""Exact pinned Windows grammar differs from the Linux artifact only by CRLF."""
import hashlib
import os
from pathlib import Path
import unittest

from test_structured_core import core_request
from jvcli.structured import StructuredProcessor, PATCH_GRAMMAR_SHA256, WINDOWS_PATCH_GRAMMAR_SHA256
from jvcli.safety import ProtocolError


class WindowsGrammar(unittest.TestCase):
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
            self.assertEqual(next(t for t in tools if t['name'] == 'apply_patch')['format']['definition'], crlf)
        else:
            with self.assertRaises(ProtocolError):
                StructuredProcessor._tools(request)
        tool['format']['definition'] += 'altered'
        with self.assertRaises(ProtocolError):
            StructuredProcessor._tools(request)
