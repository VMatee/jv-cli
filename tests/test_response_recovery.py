"""Regression coverage for succeeded JV jobs with unusable agent responses."""
import json
from pathlib import Path
import sys
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli.adapter import AdapterRuntime
from jvcli.protocol import (BASE_AGENT_INSTRUCTIONS, MAX_PROMPT_BYTES, build_jv_prompt,
                           flatten_tools, parse_agent_output, response_repair_prompt)
from jvcli.safety import Cancelled, JvError, ProtocolError, SubmissionUncertain
from jvcli.transport import JvClientConfig, NetworkError

TOOLS = [
    {'type': 'function', 'name': 'shell_command', 'parameters': {
        'type': 'object', 'required': ['command'], 'properties': {'command': {'type': 'string'}},
        'additionalProperties': False}},
    {'type': 'custom', 'name': 'apply_patch'},
]
CALL = {'type': 'tool_call', 'name': 'shell_command', 'arguments': {'command': 'pwd'}}
FINAL = {'type': 'final', 'text': 'done'}
GENERIC_ERROR = "I'm having a hard time fulfilling your request. Can I help you with something else instead?"
BAD = '{"type":"custom_tool_call","name":"apply_patch","input":"TRUNCATED'


class SequenceClient:
    """Controlled completed jobs; no credentials, files, or real model calls."""
    _token = None

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        self.config = JvClientConfig(request_timeout=1, poll_interval=.01, wait_timeout=2)
        self.pending = {}

    def submit_job(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        job_id = f'job_{len(self.prompts)}'
        self.pending[job_id] = answer if isinstance(answer, str) else json.dumps(answer)
        return {'id': job_id, 'conversation_id': job_id, 'status': 'queued'}

    def wait_for_job(self, job_id, **kwargs):
        return {'id': job_id, 'conversation_id': job_id, 'status': 'succeeded',
                'answer': self.pending[job_id]}


class ResponseRecovery(unittest.TestCase):
    def runtime(self, answers, **kwargs):
        client = SequenceClient(answers)
        return AdapterRuntime(client, **kwargs), client

    def infer(self, runtime, **kwargs):
        request = {'input': [{'role': 'user', 'content': 'create the project'},
                            {'type': 'function_call_output', 'call_id': 'already_done',
                             'output': 'ACTUAL_PRIOR_TOOL_RESULT'}], 'tools': TOOLS, **kwargs}
        prompt, catalog = build_jv_prompt(request)
        return runtime.infer(request, prompt, catalog)

    def test_malformed_then_valid_only_emits_valid_call(self):
        runtime, client = self.runtime([BAD, CALL])
        items = self.infer(runtime)
        self.assertEqual(len(items), 1)
        self.assertEqual(json.loads(items[0]['arguments']), CALL['arguments'])
        self.assertEqual(runtime.requests, 2)
        self.assertEqual(runtime.response_repairs, 1)
        self.assertEqual(runtime.last_job_id, 'job_2')
        self.assertIn('No tool from that rejected response was executed', client.prompts[1])
        self.assertIn('ACTUAL_PRIOR_TOOL_RESULT', client.prompts[1])
        self.assertNotIn('TRUNCATED', client.prompts[1])
        self.assertIn('1/2', runtime.notices.get_nowait())

    def test_generic_backend_errors_are_not_reported_as_success(self):
        for answer in (GENERIC_ERROR, {'type': 'final', 'text': GENERIC_ERROR},
                       "I encountered an error doing what you asked. Could you try again?"):
            with self.subTest(answer=answer):
                runtime, client = self.runtime([answer, CALL])
                self.assertEqual(self.infer(runtime)[0]['type'], 'function_call')
                self.assertEqual(len(client.prompts), 2)

    def test_specific_blocker_or_refusal_is_not_retried(self):
        runtime, client = self.runtime([{'type': 'final', 'text': 'I cannot perform that request: it would expose private keys.'}])
        self.assertEqual(self.infer(runtime)[0]['type'], 'message')
        self.assertEqual(len(client.prompts), 1)

    def test_repeated_invalid_output_stops_after_two_corrections(self):
        runtime, client = self.runtime([BAD, BAD, BAD, CALL])
        with self.assertRaisesRegex(ProtocolError, 'jvcli job job_3 --json'):
            self.infer(runtime)
        self.assertEqual(len(client.prompts), 3)
        self.assertEqual(runtime.response_repairs, 2)
        self.assertEqual(runtime.signatures, {})

    def test_corrected_response_is_still_checked_against_catalog(self):
        runtime, client = self.runtime([BAD, {**CALL, 'name': 'unoffered'}, {**CALL, 'arguments': {'command': 2}}])
        with self.assertRaisesRegex(ProtocolError, 'wrong type'):
            self.infer(runtime)
        self.assertEqual(runtime.signatures, {})
        self.assertEqual(len(client.prompts), 3)

    def test_invalid_batch_does_not_emit_partially_valid_tools(self):
        batch = {'type': 'tool_calls', 'calls': [CALL, {**CALL, 'name': 'unoffered'}]}
        runtime, _ = self.runtime([batch, CALL])
        self.assertEqual(len(self.infer(runtime)), 1)
        self.assertEqual(list(runtime.signatures.values()), [1])

    def test_uncertain_submission_never_resubmitted(self):
        runtime, client = self.runtime([SubmissionUncertain('ambiguous POST'), CALL])
        with self.assertRaises(SubmissionUncertain):
            self.infer(runtime)
        self.assertEqual(len(client.prompts), 1)

    def test_failed_poll_never_resubmitted(self):
        runtime, client = self.runtime([CALL, CALL])
        with patch.object(client, 'wait_for_job', side_effect=NetworkError('offline')):
            with self.assertRaises(NetworkError):
                self.infer(runtime)
        self.assertEqual(len(client.prompts), 1)

    def test_failed_server_job_never_resubmitted(self):
        runtime, client = self.runtime([CALL, CALL])
        with patch.object(client, 'wait_for_job', return_value={'status': 'failed'}):
            with self.assertRaisesRegex(JvError, 'job_1 failed'):
                self.infer(runtime)
        self.assertEqual(len(client.prompts), 1)

    def test_cancellation_prevents_correction_submission(self):
        runtime, client = self.runtime([BAD, CALL])
        original_wait = client.wait_for_job
        def stop(*args, **kwargs):
            runtime.cancel.set()
            return original_wait(*args, **kwargs)
        with patch.object(client, 'wait_for_job', side_effect=stop):
            with self.assertRaises(Cancelled):
                self.infer(runtime)
        self.assertEqual(len(client.prompts), 1)

    def test_total_request_budget_applies_to_corrections(self):
        runtime, client = self.runtime([BAD, BAD, CALL], max_requests=2)
        with self.assertRaisesRegex(ProtocolError, 'job_2'):
            self.infer(runtime)
        self.assertEqual(len(client.prompts), 2)
        self.assertEqual(runtime.requests, 2)

    def test_required_tool_choice_still_applies(self):
        runtime, client = self.runtime([FINAL, CALL])
        self.assertEqual(self.infer(runtime, tool_choice='required')[0]['type'], 'function_call')
        self.assertEqual(len(client.prompts), 2)

    def test_none_tool_choice_still_applies(self):
        runtime, client = self.runtime([CALL, FINAL])
        self.assertEqual(self.infer(runtime, tool_choice='none')[0]['type'], 'message')
        self.assertEqual(len(client.prompts), 2)

    def test_correction_prompt_is_bounded_and_does_not_truncate_original(self):
        with self.assertRaises(ProtocolError):
            response_repair_prompt('a' * MAX_PROMPT_BYTES, 'invalid JSON')
        result = response_repair_prompt('ORIGINAL', 'invalid JSON')
        self.assertTrue(result.startswith('ORIGINAL'))
        self.assertLess(len(result.encode()), MAX_PROMPT_BYTES)

    def test_begin_turn_resets_budget_and_notice_state(self):
        runtime, _ = self.runtime([BAD, CALL])
        self.infer(runtime)
        runtime.begin_turn()
        self.assertEqual(runtime.response_repairs, 0)
        self.assertEqual(runtime.requests, 0)
        self.assertTrue(runtime.notices.empty())

    def test_sse_stays_open_during_recovery_and_emits_one_call(self):
        runtime, _ = self.runtime([BAD, CALL], heartbeat=.01)
        port = runtime.start()
        try:
            payload = {'model': 'jv-local', 'input': 'inspect', 'tools': TOOLS, 'stream': True}
            request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + runtime.key})
            with urllib.request.urlopen(request, timeout=5) as response:
                events = [json.loads(line[6:]) for line in response.read().decode().splitlines()
                          if line.startswith('data: {')]
            self.assertEqual(sum(e['type'] == 'response.output_item.done' for e in events), 1)
            self.assertEqual(events[-1]['type'], 'response.completed')
            self.assertFalse(any(e['type'] in ('error', 'response.failed') for e in events))
        finally:
            runtime.close()

    def test_exhausted_recovery_sse_has_no_tool_or_success_event(self):
        runtime, _ = self.runtime([BAD, BAD, BAD], heartbeat=.01)
        port = runtime.start()
        try:
            request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/responses',
                data=json.dumps({'input': 'inspect', 'tools': TOOLS}).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + runtime.key})
            with urllib.request.urlopen(request, timeout=5) as response:
                data = response.read().decode()
            self.assertIn('response.failed', data)
            self.assertNotIn('response.completed', data)
            self.assertNotIn('response.output_item', data)
            self.assertIn('job_3', runtime.last_error)
        finally:
            runtime.close()


class MultilineProtocol(unittest.TestCase):
    catalog = flatten_tools(TOOLS)[1]

    def test_unescaped_newlines_and_tabs_preserve_patch_value(self):
        raw = '{"type":"custom_tool_call","name":"apply_patch","input":"*** Begin Patch\n*** Add File: hello.py\n+\tpass\n*** End Patch"}'
        result = parse_agent_output(raw, self.catalog)[0]
        self.assertEqual(result['input'], '*** Begin Patch\n*** Add File: hello.py\n+\tpass\n*** End Patch')

    def test_input_lines_preserve_quotes_backslashes_and_empty_lines(self):
        lines = ['*** Begin Patch', '*** Add File: a.py', r'+print("C:\\new")', '+', '*** End Patch']
        result = parse_agent_output(json.dumps({
            'type': 'custom_tool_call', 'name': 'apply_patch', 'input_lines': lines}), self.catalog)[0]
        self.assertEqual(result['input'], '\n'.join(lines))

    def test_ambiguous_input_lines_are_rejected(self):
        for fields in ({'input': 'x', 'input_lines': ['y']},
                       {'input_lines': []}, {'input_lines': ['x', 2]},
                       {'input_lines': ['x\ny']}, {'input_lines': 'xyz'}):
            with self.subTest(fields=fields):
                with self.assertRaises(ProtocolError):
                    parse_agent_output(json.dumps({'type': 'custom_tool_call', 'name': 'apply_patch', **fields}), self.catalog)

    def test_malformed_quotes_truncation_and_multiple_objects_stay_rejected(self):
        for raw in (BAD, '{"type":"custom_tool_call","name":"apply_patch","input":"+print("hello")"}',
                    json.dumps(CALL) + '\n' + json.dumps(CALL)):
            with self.subTest(raw=raw):
                with self.assertRaises(ProtocolError):
                    parse_agent_output(raw, self.catalog)

    def test_literal_newline_does_not_bypass_duplicate_key_check(self):
        raw = '{"type":"custom_tool_call","name":"apply_patch","input":"line1\nline2","input":"other"}'
        with self.assertRaises(ProtocolError):
            parse_agent_output(raw, self.catalog)

    def test_runtime_instructions_are_not_duplicated_but_other_rules_preserved(self):
        prompt, _ = build_jv_prompt({'instructions': BASE_AGENT_INSTRUCTIONS, 'input': 'hello', 'tools': TOOLS})
        self.assertEqual(prompt.count('RESPONSE CONTRACT:'), 1)
        prompt, _ = build_jv_prompt({'instructions': 'Read-only workspace', 'input': 'hello', 'tools': TOOLS})
        self.assertIn('Read-only workspace', prompt)
