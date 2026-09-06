"""Human-readable output regressions; no API calls or real user HOME changes."""
import contextlib
import io
import os
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from jvcli import cli
from jvcli.protocol import RESPONSE_CONTRACT


class TerminalOutputTests(unittest.TestCase):
    def describe(self, item, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli._describe_item(item, **kwargs)
        return out.getvalue(), err.getvalue()

    def test_multiline_shell_script_is_compact_without_execution(self):
        script = "python3 - <<'PY'\nprint('literal payload')\nPY"
        command = '/bin/bash -lc ' + shlex.quote(script)
        preview = cli._command_preview(command)
        self.assertIn("python3 - <<'PY'", preview)
        self.assertIn('3 lines; --verbose for details', preview)
        self.assertNotIn('literal payload', preview)
        self.assertNotIn('\n', preview)

    def test_simple_commands_and_malformed_quotes_stay_readable(self):
        self.assertEqual(cli._command_preview('/bin/bash -lc pwd'), 'pwd')
        self.assertEqual(cli._command_preview('echo "unfinished'), 'echo "unfinished')
        self.assertIn('--verbose for details', cli._command_preview('echo ' + 'a' * 300))

    def test_verbose_shows_command_and_success_output(self):
        command = "python3 - <<'PY'\nprint('DETAIL')\nPY"
        _, brief = self.describe({'type': 'command_execution', 'command': command}, started=True)
        _, verbose = self.describe({'type': 'command_execution', 'command': command}, started=True, verbose=True)
        self.assertNotIn('DETAIL', brief)
        self.assertIn(command, verbose)
        _, output = self.describe({'type': 'command_execution', 'exit_code': 0,
                                  'aggregated_output': 'CHECK_PASSED'}, verbose=True)
        self.assertIn('OK (exit 0)', output)
        self.assertIn('CHECK_PASSED', output)

    def test_failed_output_always_visible_and_unknown_exit_not_success(self):
        _, err = self.describe({'type': 'command_execution', 'exit_code': 1,
                               'aggregated_output': 'compiler missing'})
        self.assertIn('FAILED (exit 1)', err)
        self.assertIn('compiler missing', err)
        _, unknown = self.describe({'type': 'command_execution'})
        self.assertNotIn('OK', unknown)
        self.assertIn('not reported', unknown)

    def test_success_output_hidden_unless_verbose(self):
        _, output = self.describe({'type': 'command_execution', 'exit_code': 0,
                                  'aggregated_output': 'long diagnostic'})
        self.assertIn('OK (exit 0)', output)
        self.assertNotIn('long diagnostic', output)

    def test_changed_files_have_individual_lines_and_overflow_count(self):
        _, output = self.describe({'type': 'file_change',
                                  'changes': [{'path': f'file{i}.txt'} for i in range(14)]})
        self.assertIn('\nUpdated files:\n  - file0.txt\n  - file1.txt', output)
        self.assertIn('and 2 more', output)

    def test_answer_pipe_preserves_exact_text_and_header_is_stderr(self):
        text = 'First paragraph.\n\n```bash\npython3 -m http.server 8000\n```'
        out, err = self.describe({'type': 'agent_message', 'text': text})
        self.assertEqual(out, text + '\n')
        self.assertIn('\nAnswer\n------\n', err)

    def test_terminal_prose_wraps_and_bullets_keep_indentation(self):
        text = '- ' + 'readable words ' * 15
        result = cli._format_answer(text, 35)
        lines = result.splitlines()
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 35 for line in lines))
        self.assertTrue(all(line.startswith('  ') for line in lines[1:]))

    def test_actual_tty_display_wraps_prose(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        out = Terminal()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), patch.object(cli.shutil, 'get_terminal_size', return_value=os.terminal_size((40, 24))):
            cli._describe_item({'type': 'agent_message', 'text': 'Readable terminal text. ' * 20})
        self.assertGreater(len(out.getvalue().splitlines()), 1)
        self.assertTrue(all(len(line) <= 38 for line in out.getvalue().splitlines()))

    def test_code_urls_and_tables_are_not_rewritten(self):
        blocks = [
            '````markdown\n```python\nprint("' + 'x' * 150 + '")\n```\n````',
            '~~~bash\npython3 -m http.server 8000 --bind 127.0.0.1\n~~~',
            '    python3 -m http.server 8000 --bind 127.0.0.1',
            'Use `python3 -m http.server 8000 --bind 127.0.0.1`.',
            'https://example.invalid/' + 'x' * 150,
            '| first column | second column with a long value |',
        ]
        for block in blocks:
            with self.subTest(block=block):
                self.assertEqual(cli._format_answer(block, 30), block)

    def test_terminal_controls_are_sanitized(self):
        out, err = self.describe({'type': 'agent_message', 'text': 'safe\x1b[2Jtext'})
        self.assertNotIn('\x1b', out + err)
        self.assertNotIn('\x1b', cli._command_preview('echo \x1b[2Junsafe'))

    def test_progress_deduplicates_until_sixty_seconds_or_state_change(self):
        progress = cli._ProgressDisplay(0)
        self.assertIn('job_a', progress.update('JV job job_a: running', 15))
        self.assertIsNone(progress.update('JV job job_a: running', 30))
        self.assertIsNone(progress.update('JV job job_a: running', 60))
        self.assertEqual(progress.update('JV job job_a: running', 75),
                         'Still waiting (1m 15s elapsed).')
        self.assertIn('waiting_for_auth', progress.update('JV job job_a: waiting_for_auth', 80))
        self.assertIn('job_b', progress.update('JV job job_b: running', 90))

    def test_verbose_progress_retains_status(self):
        progress = cli._ProgressDisplay(0)
        progress.update('local command', 15, verbose=True)
        self.assertIn('local command', progress.update('local command', 30, verbose=True))

    def test_verbose_option_placement(self):
        for argv in (['--verbose'], ['--verbose', 'exec', 'task'],
                     ['exec', '--verbose', 'task'], ['resume', 'session', '--verbose']):
            self.assertTrue(cli._parser().parse_args(argv).verbose)

    def test_model_formatting_guidance_preserves_evidence_requirement(self):
        self.assertIn('Make final answers easy to read in a terminal', RESPONSE_CONTRACT)
        self.assertIn('exact run commands in fenced code blocks', RESPONSE_CONTRACT)
        self.assertIn('without confirming tool results', RESPONSE_CONTRACT)
