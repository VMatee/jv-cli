
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from jvcli import cli


FAKE_ENGINE = r"""#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.149.1")
    raise SystemExit(0)

if len(args) >= 2 and args[0] == "exec" and args[1] == "resume":
    if "--color" in args:
        print("error: unexpected argument '--color' found", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps({"type":"item.completed","item":{"id":"m2","type":"agent_message","text":"second turn ok"}}), flush=True)
    print(json.dumps({"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1}}), flush=True)
    raise SystemExit(0)

if args and args[0] == "exec":
    print(json.dumps({"type":"thread.started","thread_id":"thread_resume_test"}), flush=True)
    print(json.dumps({"type":"item.completed","item":{"id":"m1","type":"agent_message","text":"first turn ok"}}), flush=True)
    print(json.dumps({"type":"turn.completed","usage":{"input_tokens":1,"cached_input_tokens":0,"output_tokens":1}}), flush=True)
    raise SystemExit(0)

print("unexpected arguments: " + repr(args), file=sys.stderr)
raise SystemExit(3)
"""


class ResumeFlagRegressionTest(unittest.TestCase):
    def test_resume_does_not_pass_color_flag(self):
        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "codex"
            engine.write_text(FAKE_ENGINE)
            engine.chmod(0o755)

            rc1, thread_id = cli._run_engine(str(engine), "first prompt", None)
            self.assertEqual(rc1, 0)
            self.assertEqual(thread_id, "thread_resume_test")

            rc2, thread_id2 = cli._run_engine(str(engine), "second prompt", thread_id)
            self.assertEqual(rc2, 0)
            self.assertEqual(thread_id2, "thread_resume_test")


if __name__ == "__main__":
    unittest.main()
