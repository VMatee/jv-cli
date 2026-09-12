#!/usr/bin/env python3
"""Offline real-Codex reproduction: six observations, stale plan, atomic closure."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import struct
import sys
import uuid
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import cli
from jvcli.adapter import AdapterRuntime
from jvcli.agent import AgentProcessor
from jvcli.safety import JvError, private_dir
from jvcli.transport import JvClientConfig


def png(color):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + bytes(color) * 2) * 2))
        + chunk(b"IEND", b"")
    )


class Script:
    _token = None
    config = JvClientConfig(request_timeout=1, wait_timeout=5, poll_interval=0.01)

    def __init__(self):
        self.posts = []
        self.max_active = 0

    def create_response(self, body, key):
        self.posts.append((body, key))
        n = len(self.posts)
        ctx = json.loads(body["instructions"].split("JV task context (data):\n")[-1])
        observed, evidence = ctx["observations"], ctx["model_authored_evidence"]
        active = {o["sha256"] for o in observed if o["visual_content"] == "active"}
        self.max_active = max(self.max_active, len(active))
        assert len(active) <= 4
        if not ctx["plan"]:
            name, value = (
                "update_plan",
                {
                    "plan": [
                        {"step": "Inspect six sources", "status": "in_progress"},
                        {
                            "step": "Produce and verify the aggregate",
                            "status": "pending",
                        },
                        {
                            "step": "Use optional additional analysis if needed",
                            "status": "pending",
                        },
                    ]
                },
            )
        elif len(observed) > len(evidence):
            o = observed[-1]
            assert body["input"][0]["output"][0]["type"] == "input_image"
            name, value = (
                "jv_record_evidence",
                {
                    "observations": [
                        {
                            "source_call_id": o["source_call_id"],
                            "image_index": o["image_index"],
                            "sha256": o["sha256"],
                            "text": f"Scripted model observation {o['order']}",
                        }
                    ]
                },
            )
        elif len(observed) < 6:
            name, value = "view_image", {"path": f"source-{len(observed)}.png"}
        elif not any(a["name"] == "shell_command" for a in ctx["completed_actions"]):
            payload = json.dumps({"observations": [e["text"] for e in evidence]})
            name, value = (
                "shell_command",
                {
                    "command": "printf '%s\\n' "
                    + shlex.quote(payload)
                    + " > aggregate.json; printf 'once\\n' >> execution-count.txt; cat aggregate.json"
                },
            )
        elif not ctx["completion_review"]:
            assert "Scripted model observation 5" in body["input"][0]["output"]
            name, value = None, "The artifact is complete but plan metadata is stale."
        else:
            assert len(evidence) == 6 and len(observed) == 6
            assert all(s["status"] != "completed" for s in ctx["plan"])
            assert any(o["visual_content"] == "inactive_reference" for o in observed)
            name, value = (
                None,
                json.dumps(
                    {
                        "protocol": "jv-task-completion-v2",
                        "task_id": ctx["task_id"],
                        "checkpoint": ctx["checkpoint"],
                        "original_request": "Reviewed all original requirements.",
                        "evidence": "Six explicitly scripted model notes are available after eviction.",
                        "actions": "Stock Codex returned the local write/read result.",
                        "artifacts": "aggregate.json contains the six notes and was read back.",
                        "unresolved": [],
                        "plan_resolutions": [
                            {
                                "step_id": s["step_id"],
                                "resolution": "completed" if i < 2 else "not_required",
                                "reason": "Work verified by tool results."
                                if i < 2
                                else "The six observations suffice; no additional analysis is required.",
                            }
                            for i, s in enumerate(ctx["plan"])
                        ],
                        "final_answer": "COMPLETION_LIVENESS_OK",
                    }
                ),
            )
        if name:
            item = {
                "type": "function_call",
                "id": f"item_{n}",
                "call_id": f"call_{n}",
                "status": "completed",
                "name": name,
                "arguments": json.dumps(value),
            }
        else:
            item = {
                "type": "message",
                "id": f"item_{n}",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": value, "annotations": []}],
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
    assert cli._version_of_engine(args.engine) == "0.149.1"
    folder = private_dir(cli.STATE_DIR / "completion-checks" / uuid.uuid4().hex)
    workspace = private_dir(folder / "workspace")
    session = private_dir(folder / "session")
    for n in range(6):
        (workspace / f"source-{n}.png").write_bytes(png((n * 30, 20, 30)))
    client = Script()
    runtime = AdapterRuntime(
        client, processor=AgentProcessor(client, session / "structured"), heartbeat=0.1
    )
    previous = os.getcwd()
    output, errors = io.StringIO(), io.StringIO()
    try:
        os.chdir(workspace)
        port = runtime.start()
        overrides = cli._write_engine_config(
            session, port, structured=True, allow_network=False
        )
        runtime.begin_turn()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code, _ = cli._run_engine(
                args.engine,
                "Inspect six source images and write aggregate.json.",
                None,
                session_dir=session,
                overrides=overrides,
                runtime=runtime,
                turn_timeout=180,
            )
        if code or output.getvalue().strip() != "COMPLETION_LIVENESS_OK":
            raise JvError(
                f"Completion smoke failed ({code}): {errors.getvalue()[-4000:]} {output.getvalue()[-1000:]}"
            )
        task = runtime.processor.state.value["agent"]["tasks"][0]
        assert task["status"] == "committed" and task["reviews"] == 1
        assert (
            len(task["evidence"]) == 6
            and len(task["plan_reconciliation"]["resolutions"]) == 3
        )
        assert sum(a["name"] == "update_plan" for a in task["actions"]) == 1
        assert (workspace / "execution-count.txt").read_text() == "once\n"
        assert (
            len(json.loads((workspace / "aggregate.json").read_text())["observations"])
            == 6
        )
        assert len(client.posts) == 16 and runtime.response_repairs == 0
        assert len({k for _, k in client.posts}) == len(client.posts)
        print(
            json.dumps(
                {
                    "ok": True,
                    "exit_code": code,
                    "engine": "0.149.1",
                    "live_inference": False,
                    "network_enabled": False,
                    "logical_rounds": len(client.posts),
                    "visual_observations": 6,
                    "max_active_unique_images": client.max_active,
                    "model_evidence_records": 6,
                    "plan_update_calls": 1,
                    "completion_reviews": 1,
                    "atomic_plan_resolutions": 3,
                    "task_status": task["status"],
                    "exactly_once_shell_effect": True,
                    "fixture": str(folder),
                },
                indent=2,
            )
        )
    finally:
        runtime.close()
        os.chdir(previous)


if __name__ == "__main__":
    main()
