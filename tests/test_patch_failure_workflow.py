"""Offline malformed custom patch feedback, guard, and actual engine recovery."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.agent import AgentProcessor
from jvcli.safety import ProtocolError
from test_agent_completion import ScriptClient, msg, commitment
from test_structured import tool
from test_structured_core import core_request

BAD = "*** Begin Patch\n*** Update File: project/web/style.css\n@@\n.panel img{width:500px}\n*** End Patch"
ERROR = "apply_patch verification failed: invalid hunk at line 4, Unexpected line found in update hunk. Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)"


def patch_call(text, n):
    return {
        "type": "custom_tool_call",
        "name": "apply_patch",
        "call_id": f"call_{n}",
        "input": text,
    }


class PatchFailureTests(unittest.TestCase):
    def test_complete_patch_failure_and_fourth_identical_custom_action_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ScriptClient(lambda body, n: patch_call(BAD, n))
            runtime = AdapterRuntime(
                client, processor=AgentProcessor(client, Path(directory))
            )
            request = core_request()
            for n in range(3):
                call = runtime.process_request(request)[0]
                if n:
                    self.assertEqual(client.posts[n][0]["input"][0]["output"], ERROR)
                request["input"] += [
                    call,
                    {
                        "type": "custom_tool_call_output",
                        "call_id": call["call_id"],
                        "output": ERROR,
                    },
                ]
            with self.assertRaisesRegex(ProtocolError, "same tool action four times"):
                runtime.process_request(request)
            self.assertEqual(client.posts[3][0]["input"][0]["output"], ERROR)
            self.assertEqual(list(runtime.signatures.values()), [3])
            self.assertEqual(runtime.processor.state.rounds[-1]["phase"], "rejected")
            self.assertEqual(len(client.posts), 4)

    @unittest.skipUnless(
        os.environ.get("JVCLI_TEST_ENGINE")
        and os.environ.get("JVCLI_TEST_SCENARIO10_FIXTURE"),
        "explicit engine and disposable fixture source required",
    )
    def test_actual_engine_render_patch_failure_correction_and_completion(self):
        engine = os.environ["JVCLI_TEST_ENGINE"]
        self.assertEqual(cli._version_of_engine(engine), cli.ENGINE_VERSION)
        with tempfile.TemporaryDirectory(prefix="jv-patch-workflow-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            session = root / "session"
            shutil.copytree(os.environ["JVCLI_TEST_SCENARIO10_FIXTURE"], workspace)
            session.mkdir(mode=0o700)
            css = workspace / "project/web/style.css"
            original = css.read_text()
            good = (
                "*** Begin Patch\n*** Update File: project/web/style.css\n@@\n-"
                + original
                + "\n+"
                + original.replace("width:500px", "max-width:100%")
                + "\n*** End Patch"
            )

            python_check = '/usr/bin/python3 -B -c \'import sys;sys.path.insert(0,"project/python");import test_util;test_util.test_clamp();print("JV_CLAMP_OK")\''
            rust_check = "/usr/bin/cargo build --offline --manifest-path project/rust/Cargo.toml && project/rust/target/debug/jv-helper"
            repairs = "*** Begin Patch\n"
            for name, content in {
                "project/python/util.py": "def clamp(value, low, high):\n    return max(low, min(high, value))\n",
                "project/rust/src/main.rs": 'fn main(){let values=[1,2,3];println!("sum={}",values.iter().sum::<i32>()); }\n',
                "project/docs/README.md": "Python, Rust, documentation and UI repaired and verified.\n",
            }.items():
                repairs += f"*** Update File: {name}\n@@\n"
                repairs += "".join(
                    "-" + line + "\n"
                    for line in (workspace / name).read_text().splitlines()
                )
                repairs += "".join("+" + line + "\n" for line in content.splitlines())
            repairs += "*** End Patch"

            def shell(command):
                return tool(json.dumps({"command": command}))

            def script(body, n):
                if n == 1:
                    return shell(python_check)
                if n == 2:
                    self.assertIn("AssertionError", body["input"][0]["output"])
                    return shell(rust_check)
                if n == 3:
                    self.assertIn("sum=3", body["input"][0]["output"])
                    return shell("/usr/bin/python3 -B render_ui.py before")
                if n == 4:
                    self.assertIn(
                        "JV_SCENARIO10_RENDER_OK before", body["input"][0]["output"]
                    )
                    return patch_call(BAD, n)
                if n == 5:
                    failure = body["input"][0]["output"]
                    self.assertIn("apply_patch verification failed", failure)
                    self.assertIn("Every line should start", failure)
                    return patch_call(good, n)
                if n == 6:
                    self.assertIn("Success", body["input"][0]["output"])
                    return patch_call(repairs, n)
                if n == 7:
                    self.assertIn("Success", body["input"][0]["output"])
                    return shell("/usr/bin/python3 -B render_ui.py after")
                if n == 8:
                    self.assertIn(
                        "JV_SCENARIO10_RENDER_OK after", body["input"][0]["output"]
                    )
                    return shell(python_check + " && " + rust_check)
                if n == 9:
                    self.assertIn("JV_CLAMP_OK", body["input"][0]["output"])
                    self.assertIn("sum=6", body["input"][0]["output"])
                    return msg("Synthetic repository workflow complete.")
                self.assertEqual(n, 10)
                return msg(json.dumps(commitment(body, "PATCH_RECOVERY_OK")))

            client = ScriptClient(script)
            runtime = AdapterRuntime(
                client, processor=AgentProcessor(client, session / "structured")
            )
            previous = Path.cwd()
            try:
                os.chdir(workspace)
                port = runtime.start()
                overrides = cli._write_engine_config(
                    session, port, structured=True, allow_network=True
                )
                runtime.begin_turn()
                output, errors = io.StringIO(), io.StringIO()
                with (
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    code, _ = cli._run_engine(
                        engine,
                        "Run the synthetic local CSS workflow.",
                        None,
                        session_dir=session,
                        overrides=overrides,
                        runtime=runtime,
                        turn_timeout=90,
                    )
                self.assertEqual(code, 0, errors.getvalue())
                self.assertEqual(output.getvalue().strip(), "PATCH_RECOVERY_OK")
                self.assertEqual(runtime.processor.last_completion, "committed")
                self.assertEqual(len(client.posts), 10)
                self.assertEqual(len({key for _, key in client.posts}), 10)
                self.assertNotEqual(
                    (workspace / "project/reports/ui-before.png").read_bytes(),
                    (workspace / "project/reports/ui-after.png").read_bytes(),
                )
                self.assertFalse(list(workspace.glob(".scenario10-render-*")))
                self.assertIn("max-width:100%", css.read_text())
            finally:
                os.chdir(previous)
                runtime.close()
