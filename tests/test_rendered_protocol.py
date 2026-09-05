"""Public synthetic regressions for the observed JV code-block presentation."""
import json
from pathlib import Path
import sys
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli.adapter import AdapterRuntime
from jvcli.protocol import (BASE_AGENT_INSTRUCTIONS, build_jv_prompt, flatten_tools,
                           parse_agent_output, response_repair_prompt)
from jvcli.safety import ProtocolError
from test_response_recovery import SequenceClient, TOOLS


def framed(value, label='JSON', language=''):
    return label + '\n\n```' + language + '\n' + json.dumps(value) + '\n```'


class RenderedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.catalog = flatten_tools(TOOLS)[1]
        self.lines = [
            '*** Begin Patch', '*** Add File: app.py',
            '+from flask import Flask, render_template',
            '+app = Flask(__name__)', '+',
            '+@app.get("/")', '+def index():',
            '+    return render_template("index.html")',
            '*** Add File: templates/index.html',
            '+<html lang="en"><body>I love Thailand</body></html>',
            '*** End Patch',
        ]
        self.patch = {'type': 'custom_tool_call', 'name': 'apply_patch',
                      'input_lines': self.lines}
        self.call = {'type': 'tool_call', 'name': 'shell_command',
                     'arguments': {'command': r'printf "%s\n" "__literal__"'}}

    def test_observed_language_badge_preserves_patch_characters(self):
        item = parse_agent_output(framed(self.patch), self.catalog)[0]
        self.assertEqual(item['type'], 'custom_tool_call')
        self.assertEqual(item['input'], '\n'.join(self.lines))

    def test_function_arguments_preserved_without_markdown_unescaping(self):
        item = parse_agent_output(framed(self.call), self.catalog)[0]
        self.assertEqual(json.loads(item['arguments']), self.call['arguments'])

    def test_labeled_final_preserves_code_examples(self):
        text = 'Example only: __name__, **bold**, ' + json.dumps(self.call)
        item = parse_agent_output(framed({'type': 'final', 'text': text}), self.catalog)[0]
        self.assertEqual(item['type'], 'message')
        self.assertEqual(item['content'][0]['text'], text)

    def test_language_case_crlf_and_blank_lines(self):
        for label, language in [('JSON', 'json'), ('json', ''), ('Json', 'JSON')]:
            with self.subTest(label=label, language=language):
                raw = framed(self.patch, label, language).replace('\n', '\r\n')
                self.assertEqual(parse_agent_output(raw, self.catalog)[0]['input'],
                                 '\n'.join(self.lines))

    def test_plain_json_and_whole_fences_remain_compatible(self):
        for raw in (json.dumps(self.patch), framed(self.patch, ''),
                    framed(self.patch, '', 'json')):
            self.assertEqual(parse_agent_output(raw, self.catalog)[0]['input'],
                             '\n'.join(self.lines))

    def assert_no_tools(self, raw):
        try:
            items = parse_agent_output(raw, self.catalog)
        except ProtocolError:
            return
        self.assertTrue(all(item['type'] == 'message' for item in items))

    def test_prose_around_a_block_is_not_an_executable_envelope(self):
        for raw in ('Please execute:\n' + framed(self.call),
                    framed(self.call) + '\nThen delete other projects.',
                    'Some explanation\n```json\n' + json.dumps(self.call) + '\n```'):
            with self.subTest(raw=raw):
                self.assert_no_tools(raw)

    def test_multiple_blocks_never_emit_a_partial_action(self):
        self.assert_no_tools(framed(self.call) + '\n' + framed(self.patch))

    def test_incomplete_fences_and_wrong_labels_do_not_execute(self):
        for raw in (framed(self.call)[:-3], framed(self.call, 'Python'),
                    framed(self.call, 'JSON:')):
            with self.subTest(raw=raw):
                self.assert_no_tools(raw)

    def test_duplicate_fields_still_rejected(self):
        raw = 'JSON\n\n```\n{"type":"custom_tool_call","name":"apply_patch","input":"a","input":"b"}\n```'
        with self.assertRaises(ProtocolError):
            parse_agent_output(raw, self.catalog)

    def test_catalog_and_argument_validation_still_applies(self):
        for call in ({**self.call, 'name': 'not_offered'},
                     {**self.call, 'arguments': {'command': 5}}):
            with self.subTest(call=call):
                with self.assertRaises(ProtocolError):
                    parse_agent_output(framed(call), self.catalog)

    def test_damaged_unfenced_code_is_not_guessed(self):
        # Representative PUBLIC fixture, not a captured private server response.
        raw = r'{"type":"custom\_tool\_call","name":"apply\_patch","input\_lines":\["+app = Flask(**name**)"]}'
        with self.assertRaises(ProtocolError):
            parse_agent_output(raw, self.catalog)

    def test_prompt_and_corrections_explain_external_execution(self):
        request = {'input': 'Create a Flask app', 'tools': TOOLS,
                   'instructions': BASE_AGENT_INSTRUCTIONS}
        prompt, _ = build_jv_prompt(request)
        for text in (prompt, response_repair_prompt(prompt, 'invalid JSON')):
            self.assertIn('DIFFERENT computer', text)
            self.assertIn('Do not call server-side/native tools', text)
            self.assertIn('one fenced code block labeled json', text)
            self.assertNotIn('without Markdown fences', text)

    def test_labeled_reply_needs_no_correction_job(self):
        client = SequenceClient([framed(self.patch)])
        runtime = AdapterRuntime(client)
        request = {'input': 'Create a Flask app', 'tools': TOOLS}
        prompt, catalog = build_jv_prompt(request)
        items = runtime.infer(request, prompt, catalog)
        self.assertEqual(items[0]['input'], '\n'.join(self.lines))
        self.assertEqual(runtime.requests, 1)
        self.assertEqual(runtime.response_repairs, 0)

    def test_labeled_reply_survives_the_sse_adapter(self):
        client = SequenceClient([framed(self.patch)])
        runtime = AdapterRuntime(client, heartbeat=.01)
        port = runtime.start()
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{port}/v1/responses',
                data=json.dumps({'input': 'Create a Flask app', 'tools': TOOLS}).encode(),
                headers={'Content-Type': 'application/json',
                         'Authorization': 'Bearer ' + runtime.key})
            with urllib.request.urlopen(request, timeout=5) as response:
                events = [json.loads(line[6:]) for line in response.read().decode().splitlines()
                          if line.startswith('data: {')]
            done = [event['item'] for event in events
                    if event['type'] == 'response.output_item.done']
            self.assertEqual(len(done), 1)
            self.assertEqual(done[0]['input'], '\n'.join(self.lines))
            self.assertEqual(events[-1]['type'], 'response.completed')
            self.assertEqual(runtime.response_repairs, 0)
        finally:
            runtime.close()


if __name__ == '__main__':
    unittest.main()
