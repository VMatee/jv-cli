"""Offline multi-patch regression through the real engine and local adapter.

Set JVCLI_TEST_ENGINE to an existing pinned executable to enable. All model
responses are scripted; no account, public API, or operator reservation is used.
"""

import contextlib
import io
import json
import os
import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.agent import AgentProcessor
from jvcli.safety import ProtocolError
from test_agent_completion import ScriptClient, commitment, msg
from test_structured import tool
from test_structured_core import core_request

ORIGINAL = (
    "def average(values):\n"
    "    if not values:\n"
    "        return 0 / 0  # bug\n"
    "    return sum(values) / (len(values) + 1)  # bug\n\n"
    "def label(value):\n"
    '    return f"result : {value}"  # formatting bug\n'
)
PATCHES = [
    (
        "*** Begin Patch\n*** Update File: calculator.py\n@@\n"
        "-        return 0 / 0  # bug\n+        return 0\n*** End Patch"
    ),
    (
        "*** Begin Patch\n*** Update File: calculator.py\n@@\n"
        "-    return sum(values) / (len(values) + 1)  # bug\n"
        "+    return sum(values) / len(values)\n@@\n"
        '-    return f"result : {value}"  # formatting bug\n'
        '+    return f"result: {value}"\n*** End Patch'
    ),
]
TESTS = """import unittest
from calculator import average, label
class CalculatorTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(average([]), 0)
    def test_average(self): self.assertEqual(average([2,4,6]), 4)
    def test_label(self): self.assertEqual(label(5), "result: 5")
if __name__ == "__main__": unittest.main()
"""


def scripted(body, n):
    if n == 1:
        return tool(
            json.dumps({"command": f"{shlex.quote(sys.executable)} -B check_calc.py"})
        )
    if n in (2, 3, 4):
        previous = body["input"][0]
        assert body["previous_response_id"] == f"response_{n - 1}"
        assert previous["call_id"] == f"call_{n - 1}"
        if n == 2:
            assert previous["type"] == "function_call_output"
            assert "FAILED (failures=2, errors=1)" in previous["output"]
        else:
            assert previous["type"] == "custom_tool_call_output"
            assert "Success. Updated" in previous["output"]
        if n < 4:
            return {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": f"call_{n}",
                "input": PATCHES[n - 2],
            }
        return tool(
            json.dumps({"command": f"{shlex.quote(sys.executable)} -B check_calc.py"})
        )
    if n == 5:
        assert "OK" in body["input"][0]["output"]
        assert re.search(
            r"(?:Process exited with code |Exit code: )0", body["input"][0]["output"]
        )
        return msg("Tests pass after two separate patches.")
    assert n == 6
    return msg(json.dumps(commitment(body, "MULTI_PATCH_OK")))


class MultiPatchTests(unittest.TestCase):
    def test_distinct_patches_allowed_and_republication_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ScriptClient(scripted)
            runtime = AdapterRuntime(
                client, processor=AgentProcessor(client, Path(directory))
            )
            request = core_request()
            outputs = [
                "FAILED (failures=2, errors=1)",
                "Success. Updated calculator.py",
                "Success. Updated calculator.py",
                "Process exited with code 0\nOK",
            ]
            for result in outputs:
                call = runtime.process_request(request)[0]
                before = len(client.posts)
                with self.assertRaisesRegex(ProtocolError, "twice"):
                    runtime.process_request(request)
                self.assertEqual(len(client.posts), before)
                request["input"] += [
                    call,
                    {
                        "type": call["type"] + "_output",
                        "call_id": call["call_id"],
                        "output": result,
                    },
                ]
            self.assertEqual(
                runtime.process_request(request)[0]["content"][0]["text"],
                "MULTI_PATCH_OK",
            )
            self.assertEqual(runtime.processor.last_completion, "committed")
            self.assertEqual(len(client.posts), 6)
            self.assertEqual(len({key for _, key in client.posts}), 6)

    @unittest.skipUnless(
        os.environ.get("JVCLI_TEST_ENGINE"), "explicit pinned engine required"
    )
    def test_actual_shell_patch_and_completion(self):
        engine = os.environ["JVCLI_TEST_ENGINE"]
        self.assertEqual(cli._version_of_engine(engine), cli.ENGINE_VERSION)
        with tempfile.TemporaryDirectory(prefix="jv-multi-patch-") as directory:
            root = Path(directory)
            workspace, session = root / "workspace", root / "session"
            workspace.mkdir(mode=0o700)
            session.mkdir(mode=0o700)
            (workspace / "calculator.py").write_text(ORIGINAL)
            (workspace / "check_calc.py").write_text(TESTS)
            client = ScriptClient(scripted)
            runtime = AdapterRuntime(
                client, processor=AgentProcessor(client, session / "structured")
            )
            previous = Path.cwd()
            try:
                os.chdir(workspace)
                port = runtime.start()
                overrides = cli._write_engine_config(
                    session, port, structured=True, allow_network=False
                )
                runtime.begin_turn()
                output, errors = io.StringIO(), io.StringIO()
                with (
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    code, _ = cli._run_engine(
                        engine,
                        "Repair the synthetic calculator and verify it.",
                        None,
                        session_dir=session,
                        overrides=overrides,
                        runtime=runtime,
                        turn_timeout=60,
                    )
                self.assertEqual(code, 0, errors.getvalue())
                self.assertEqual(output.getvalue().strip(), "MULTI_PATCH_OK")
                self.assertEqual(runtime.processor.last_completion, "committed")
                self.assertEqual(len(client.posts), 6)
                self.assertEqual(len({key for _, key in client.posts}), 6)
                calls = [
                    r["output"]
                    for r in runtime.processor.state.rounds
                    if r.get("output", {}).get("name")
                ]
                self.assertEqual(
                    [c["name"] for c in calls],
                    ["shell_command", "apply_patch", "apply_patch", "shell_command"],
                )
                self.assertEqual(
                    [c["input"] for c in calls if c["name"] == "apply_patch"], PATCHES
                )
                self.assertEqual((workspace / "check_calc.py").read_text(), TESTS)
                self.assertNotIn("# bug", (workspace / "calculator.py").read_text())
            finally:
                os.chdir(previous)
                runtime.close()
