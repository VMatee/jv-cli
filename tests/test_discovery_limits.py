"""Synthetic loop regressions: these tests never invoke or install Rust."""
import json
from pathlib import Path
import sys
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli.adapter import AdapterRuntime, rust_discovery_probe
from jvcli.protocol import BASE_AGENT_INSTRUCTIONS, build_jv_prompt
from jvcli.safety import ProtocolError
from test_response_recovery import SequenceClient, TOOLS


def call(command):
    return {'type': 'tool_call', 'name': 'shell_command',
            'arguments': {'command': command}}


class DiscoveryLimitsTests(unittest.TestCase):
    def infer(self, runtime):
        request = {'input': 'Source-only task; do not install Rust', 'tools': TOOLS}
        prompt, catalog = build_jv_prompt(request)
        return runtime.infer(request, prompt, catalog)

    def test_observed_discovery_variants(self):
        for command in (
            'which cargo rustc rustup 2>&1 || find /usr /home -name cargo 2>/dev/null',
            'which rustc cargo rustup || find / -name cargo 2>/dev/null',
            'export PATH="$HOME/.cargo/bin:$PATH"; cargo --version',
            'PATH="/explicit/toolchain/bin:$PATH" CARGO_HOME="/explicit/cargo" rustc --version',
            'command -v cargo || echo cargo_not_found',
            'type rustc', 'rustup show', 'rustup toolchain list',
            'find "$HOME" -name cargo 2>/dev/null',
            'echo checking\ncargo --version'):
            with self.subTest(command=command):
                self.assertTrue(rust_discovery_probe(command))

    def test_edits_builds_and_quoted_examples_are_not_probes(self):
        for command in (
            'cargo build', 'cargo check', 'cargo run', 'cargo test',
            'rustup toolchain install stable', 'python3 --version',
            'printf "%s" "which cargo"', 'echo "cargo --version"',
            'find . -name Cargo.toml', 'find . -maxdepth 2 -type f',
            "python3 - <<'PY'\nprint('which cargo')\nPY",
            'echo "unterminated', 'cat src/main.rs'):
            with self.subTest(command=command):
                self.assertFalse(rust_discovery_probe(command))

    def test_seventh_variant_stops_without_correction_jobs(self):
        runtime = AdapterRuntime(SequenceClient(
            [call(f'command -v cargo; echo probe{i}') for i in range(7)]))
        for _ in range(6):
            self.assertEqual(self.infer(runtime)[0]['type'], 'function_call')
        with self.assertRaisesRegex(ProtocolError, 'Rust prerequisite discovery limit'):
            self.infer(runtime)
        self.assertEqual(runtime.rust_discovery_probes, 6)
        self.assertEqual(runtime.requests, 7)
        self.assertEqual(runtime.response_repairs, 0)

    def test_limit_is_atomic_for_mixed_batch(self):
        batch = {'type': 'tool_calls', 'calls': [
            call('touch should-not-run'), call('command -v rustc')]}
        runtime = AdapterRuntime(SequenceClient([batch]))
        runtime.rust_discovery_probes = 6
        with self.assertRaisesRegex(ProtocolError, 'no tools from this response'):
            self.infer(runtime)
        self.assertEqual(runtime.signatures, {})
        self.assertEqual(runtime.rust_discovery_probes, 6)

    def test_rejected_protocol_does_not_count_as_discovery(self):
        runtime = AdapterRuntime(SequenceClient([
            {'type': 'tool_calls', 'calls': [call('which cargo'),
                {'type': 'tool_call', 'name': 'not_offered', 'arguments': {}}]},
            {'type': 'final', 'text': 'Compiler missing; source not compiled.'}]))
        self.assertEqual(self.infer(runtime)[0]['type'], 'message')
        self.assertEqual(runtime.rust_discovery_probes, 0)

    def test_begin_turn_resets_discovery_and_exact_action_counts(self):
        runtime = AdapterRuntime(SequenceClient([call('which cargo')] * 2))
        self.infer(runtime)
        runtime.begin_turn()
        self.assertEqual(runtime.rust_discovery_probes, 0)
        self.assertEqual(runtime.signatures, {})
        self.infer(runtime)
        self.assertEqual(runtime.rust_discovery_probes, 1)

    def test_final_missing_prerequisite_is_not_retried(self):
        text = 'Rust is missing. Source files are ready; compilation was not tested. No installation performed.'
        runtime = AdapterRuntime(SequenceClient([{'type': 'final', 'text': text}]))
        runtime.rust_discovery_probes = 6
        self.assertEqual(self.infer(runtime)[0]['content'][0]['text'], text)
        self.assertEqual(runtime.requests, 1)

    def test_build_remains_allowed_after_discovery_budget(self):
        runtime = AdapterRuntime(SequenceClient([call('cargo build')]))
        runtime.rust_discovery_probes = 6
        self.assertEqual(self.infer(runtime)[0]['type'], 'function_call')

    def test_identical_limit_remains_and_counters_are_atomic(self):
        runtime = AdapterRuntime(SequenceClient([call('pwd')] * 4))
        for _ in range(3):
            self.infer(runtime)
        with self.assertRaisesRegex(ProtocolError, 'same tool action four times'):
            self.infer(runtime)
        self.assertEqual(list(runtime.signatures.values()), [3])

    def test_argument_order_and_spacing_cannot_bypass_identical_limit(self):
        runtime = AdapterRuntime(SequenceClient([{'type': 'final', 'text': 'fixture'}] * 4))
        for index in range(4):
            arguments = ('{"command":"pwd","timeout_ms":1}' if index % 2
                         else '{ "timeout_ms": 1, "command": "pwd" }')
            item = {'type': 'function_call', 'name': 'shell_command', 'arguments': arguments}
            with patch('jvcli.adapter.parse_agent_output', return_value=[item]):
                if index < 3:
                    self.infer(runtime)
                else:
                    with self.assertRaisesRegex(ProtocolError, 'same tool action'):
                        self.infer(runtime)

    def test_discovery_limit_emits_error_without_tool_sse_events(self):
        runtime = AdapterRuntime(SequenceClient([{'type': 'tool_calls', 'calls': [
            call('touch must-not-run'), call('which cargo')]}]))
        runtime.rust_discovery_probes = 6
        port = runtime.start()
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{port}/v1/responses',
                data=json.dumps({'input': 'source only', 'tools': TOOLS}).encode(),
                headers={'Content-Type': 'application/json',
                         'Authorization': 'Bearer ' + runtime.key})
            with urllib.request.urlopen(request, timeout=5) as response:
                events = [json.loads(line[6:]) for line in response.read().decode().splitlines()
                          if line.startswith('data: {')]
            self.assertFalse(any(e['type'].startswith('response.output_item') for e in events))
            self.assertFalse(any(e['type'] == 'response.completed' for e in events))
            self.assertIn('Rust prerequisite discovery limit', json.dumps(events))
            self.assertEqual(runtime.signatures, {})
        finally:
            runtime.close()

    def test_instruction_scope_and_shell_environment_are_explicit(self):
        for fragment in ("do not borrow another project's private toolchain",
                         'Do not install Rust', 'Shell exports do not persist',
                         'compilation was not tested'):
            self.assertIn(fragment, BASE_AGENT_INSTRUCTIONS)
