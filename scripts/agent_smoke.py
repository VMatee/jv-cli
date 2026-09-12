#!/usr/bin/env python3
"""Real pinned Codex with scripted JV inference and local evidence/completion."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.agent import EVIDENCE_TOOL, AgentProcessor
from jvcli.safety import JvError, private_dir
from jvcli.transport import JvClientConfig
from parity_smoke import tiny_png


class Script:
    _token = None
    config = JvClientConfig(request_timeout=1, wait_timeout=5, poll_interval=0.01)

    def __init__(self):
        self.posts = []

    def create_response(self, body, key):
        self.posts.append((body, key))
        n = len(self.posts)
        ctx = json.loads(body["instructions"].split("JV task context (data):\n")[-1])
        if n == 1:
            name, args = "view_image", {"path": "source.png"}
        elif n == 2:
            observation = ctx["observations"][0]
            assert body["input"][0]["type"] == "function_call_output"
            assert body["input"][0]["output"][0]["type"] == "input_image"
            name, args = (
                EVIDENCE_TOOL,
                {
                    "observations": [
                        {
                            "source_call_id": observation["source_call_id"],
                            "image_index": observation["image_index"],
                            "sha256": observation["sha256"],
                            "text": "Synthetic model-authored observation of the fixture.",
                        }
                    ]
                },
            )
        elif n in (3, 7):
            name, args = None, "An intentionally premature final; work remains."
        elif n == 4:
            assert ctx["completion_review"]
            assert len(ctx["model_authored_evidence"]) == 1
            name, args = (
                "shell_command",
                {
                    "command": "printf 'AGENT_ARTIFACT_OK\\n' > artifact.txt; cat artifact.txt"
                },
            )
        elif n in (5, 8):
            if n == 5:
                assert "AGENT_ARTIFACT_OK" in body["input"][0]["output"]
            assert ctx["completion_review"]
            name, args = (
                None,
                json.dumps(
                    {
                        "protocol": "jv-task-completion-v2",
                        "task_id": ctx["task_id"],
                        "checkpoint": ctx["checkpoint"],
                        "original_request": "Reviewed the original workspace request.",
                        "evidence": "Reviewed the persisted model observation.",
                        "actions": "The actual shell result confirms artifact creation.",
                        "artifacts": "artifact.txt read back successfully.",
                        "unresolved": [],
                        "plan_resolutions": [],
                        "final_answer": "AGENT_SMOKE_OK",
                    }
                ),
            )
        elif n == 6:
            # A fresh user turn on the same stock Codex thread uses the same
            # canonical Server chain, not a lossy replay into a new conversation.
            assert body.get("previous_response_id") == "response_5"
            assert len(body["input"]) == 1 and body["input"][0]["role"] == "user"
            name, args = "shell_command", {"command": "cat artifact.txt"}
        else:
            raise JvError("Unexpected scripted inference")
        if name:
            item = {
                "type": "function_call",
                "id": f"item_{n}",
                "call_id": f"call_{n}",
                "status": "completed",
                "name": name,
                "arguments": json.dumps(args),
            }
        else:
            item = {
                "type": "message",
                "id": f"item_{n}",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": args, "annotations": []}],
            }
        return {
            "id": f"response_{n}",
            "object": "response",
            "status": "completed",
            "output": [item],
            "error": None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    args = parser.parse_args()
    if cli._version_of_engine(args.engine) != "0.149.1":
        raise JvError("Embedded engine must remain exactly 0.149.1")
    folder = private_dir(cli.STATE_DIR / "agent-checks" / uuid.uuid4().hex)
    workspace = private_dir(folder / "workspace")
    session = private_dir(folder / "session")
    (workspace / "source.png").write_bytes(tiny_png())
    previous = os.getcwd()
    client = Script()
    thread = None
    results = []
    try:
        os.chdir(workspace)
        for prompt in (
            "Inspect source.png and produce artifact.txt.",
            "Read the produced artifact and confirm it.",
        ):
            runtime = AdapterRuntime(
                client,
                processor=AgentProcessor(client, session / "structured"),
                heartbeat=0.1,
            )
            output, errors = io.StringIO(), io.StringIO()
            try:
                port = runtime.start()
                overrides = cli._write_engine_config(
                    session, port, structured=True, allow_network=False
                )
                runtime.begin_turn()
                with (
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    code, thread = cli._run_engine(
                        args.engine,
                        prompt,
                        thread,
                        session_dir=session,
                        overrides=overrides,
                        runtime=runtime,
                        turn_timeout=90,
                    )
                if code or output.getvalue().strip() != "AGENT_SMOKE_OK":
                    raise JvError(
                        f"Agent smoke failed ({code}): {errors.getvalue()[-6000:]} {output.getvalue()[-1000:]}"
                    )
                assert runtime.processor.last_completion == "committed"
                assert runtime.response_repairs == 0
                results.append(
                    {"exit_code": code, "completion": "committed", "network": False}
                )
            finally:
                runtime.close()
        assert len(client.posts) == 8
        assert (workspace / "artifact.txt").read_text() == "AGENT_ARTIFACT_OK\n"
        print(
            json.dumps(
                {
                    "ok": True,
                    "engine": "0.149.1",
                    "live_inference": False,
                    "checks": results,
                    "logical_rounds": len(client.posts),
                    "client_tools": 3,
                    "model_evidence_commits": 1,
                    "completion_commits": 2,
                    "fixture": str(folder),
                },
                indent=2,
            )
        )
    finally:
        os.chdir(previous)


if __name__ == "__main__":
    main()
