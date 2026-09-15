"""Plan reconciliation is model-authored, task-bound and durably atomic."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_agent_completion as support
from jvcli.adapter import AdapterRuntime
from jvcli.agent import MAX_REVIEWS, AgentProcessor
from jvcli.safety import JvError, ProtocolError
from jvcli.structured import _digest
from test_agent_completion import commitment, context, msg
from test_structured import tool
from test_structured_core import core_request

PLAN = [
    {"step": "Inspect inputs", "status": "in_progress"},
    {"step": "Produce requested artifact", "status": "pending"},
    {"step": "Optional analysis if needed", "status": "pending"},
]


def resolved(body, states=None):
    value = commitment(body)
    opened = [
        s
        for s in context(body)["plan"]
        if s["status"] not in {"completed", "superseded", "not_required"}
    ]
    value["plan_resolutions"] = [
        {
            "step_id": s["step_id"],
            "resolution": states[i] if states else "completed",
            "reason": "Model reviewed the completed actions and original requirements.",
        }
        for i, s in enumerate(opened)
    ]
    return value


class Crash(BaseException):
    pass


class PlanCompletionTests(unittest.TestCase):
    runtime = support.AgentTests.runtime
    result = support.AgentTests.result

    def script(self, body, n):
        if n == 1:
            return tool(json.dumps({"plan": PLAN}), name="update_plan")
        if n == 2:
            return msg("Substantive work complete; progress metadata is stale")
        return msg(json.dumps(resolved(body)))

    def start(self, directory, script=None):
        client, runtime = self.runtime(directory, script or self.script)
        request = core_request()
        call = runtime.process_request(request)[0]
        self.result(request, call, "Plan updated")
        return client, runtime, request

    def task(self, runtime):
        return runtime.processor.state.value["agent"]["tasks"][-1]

    def test_atomic_stale_plan_completion_without_housekeeping_tool(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td)
            final = runtime.process_request(request)
            self.assertEqual(final[0]["content"][0]["text"], "DONE")
            task = self.task(runtime)
            self.assertEqual(task["status"], "committed")
            self.assertEqual([s["status"] for s in task["plan"]], ["completed"] * 3)
            self.assertEqual(
                [s["status"] for s in task["plan_reconciliation"]["plan_before"]],
                ["in_progress", "pending", "pending"],
            )
            self.assertEqual(task["plan_reconciliation"]["authorship"], "model")
            self.assertEqual(len(client.posts), 3)
            self.assertEqual(task["reviews"], 1)
            self.assertEqual([a["name"] for a in task["actions"]], ["update_plan"])

    def test_explicit_superseded_and_not_required(self):
        def script(body, n):
            if n < 3:
                return self.script(body, n)
            return msg(
                json.dumps(resolved(body, ["completed", "superseded", "not_required"]))
            )

        with tempfile.TemporaryDirectory() as td:
            _, runtime, request = self.start(td, script)
            runtime.process_request(request)
            self.assertEqual(
                [s["status"] for s in self.task(runtime)["plan"]],
                ["completed", "superseded", "not_required"],
            )

    def test_invalid_resolution_matrix_never_mutates_plan(self):
        cases = {
            "omitted": lambda v: v["plan_resolutions"].pop(),
            "unknown": lambda v: v["plan_resolutions"][0].update(step_id="foreign"),
            "duplicate": lambda v: v["plan_resolutions"].append(
                v["plan_resolutions"][0]
            ),
            "invalid_state": lambda v: v["plan_resolutions"][0].update(
                resolution="unfinished"
            ),
            "missing_reason": lambda v: v["plan_resolutions"][0].pop("reason"),
            "not_required_reason": lambda v: v["plan_resolutions"][0].update(
                resolution="not_required", reason=""
            ),
            "superseded_reason": lambda v: v["plan_resolutions"][0].update(
                resolution="superseded", reason="  "
            ),
            "long_reason": lambda v: v["plan_resolutions"][0].update(reason="x" * 1025),
            "nonstring_id": lambda v: v["plan_resolutions"][0].update(step_id=[]),
            "extra_field": lambda v: v["plan_resolutions"][0].update(trusted=True),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:

                def script(body, n, mutate=mutate):
                    if n < 3:
                        return self.script(body, n)
                    v = resolved(body)
                    mutate(v)
                    return msg(json.dumps(v))

                client, runtime, request = self.start(td, script)
                with self.assertRaisesRegex(ProtocolError, "PLAN-RESOLUTION"):
                    runtime.process_request(request)
                self.assertEqual(
                    [s["status"] for s in self.task(runtime)["plan"]],
                    [s["status"] for s in PLAN],
                )
                self.assertNotIn("commitment", self.task(runtime))
                self.assertEqual(len(client.posts), 3)

    def test_unresolved_requirements_override_resolved_plan_and_exhaust_budget(self):
        def script(body, n):
            if n < 3:
                return self.script(body, n)
            v = resolved(body)
            v["unresolved"] = ["Promised artifact is unfinished"]
            return msg(json.dumps(v))

        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td, script)
            with self.assertRaisesRegex(JvError, "COMPLETION-BUDGET"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 2 + MAX_REVIEWS)
            self.assertEqual(self.task(runtime)["reviews"], 3)
            self.assertNotIn("plan_reconciliation", self.task(runtime))

    def test_unresolved_task_continues_tools_then_resolves_without_update_plan(self):
        def script(body, n):
            if n < 3:
                return self.script(body, n)
            if n == 3:
                v = resolved(body)
                v["unresolved"] = ["Artifact still required"]
                return msg(json.dumps(v))
            if n == 4:
                return tool('{"command":"create artifact"}')
            return msg(json.dumps(resolved(body)))

        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td, script)
            call = runtime.process_request(request)[0]
            self.assertEqual(call["name"], "shell_command")
            self.assertNotIn("plan_reconciliation", self.task(runtime))
            self.result(request, call, "Artifact created and read back")
            runtime.process_request(request)
            self.assertEqual(self.task(runtime)["status"], "committed")
            self.assertEqual(len(client.posts), 5)

    def test_stale_task_checkpoint_and_mutated_canonical_plan(self):
        for kind in ("task", "checkpoint", "plan"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                holder = {}

                def script(body, n, kind=kind, holder=holder):
                    if n < 3:
                        return self.script(body, n)
                    v = resolved(body)
                    if kind == "plan":
                        self.task(holder["runtime"])["plan"][0]["step"] = (
                            "Changed canonical intent"
                        )
                    else:
                        v["task_id" if kind == "task" else "checkpoint"] = "stale"
                    return msg(json.dumps(v))

                _client, runtime, request = self.start(td, script)
                holder["runtime"] = runtime
                with self.assertRaisesRegex(ProtocolError, "COMPLETION-INTEGRITY"):
                    runtime.process_request(request)
                self.assertNotIn("commitment", self.task(runtime))

    def test_missing_tool_result_never_reaches_completion_inference(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, lambda b, n: tool())
            request = core_request()
            call = runtime.process_request(request)[0]
            request["input"].append(call)
            with self.assertRaisesRegex(ProtocolError, "unresolved|Incomplete|missing"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 1)

    def test_already_completed_plan_and_no_explicit_plan(self):
        for plan in ([], [{"step": "Done", "status": "completed"}]):
            with self.subTest(plan=plan), tempfile.TemporaryDirectory() as td:

                def script(body, n, plan=plan):
                    if n == 1:
                        return (
                            tool(json.dumps({"plan": plan}), name="update_plan")
                            if plan
                            else tool()
                        )
                    return (
                        msg("candidate") if n == 2 else msg(json.dumps(resolved(body)))
                    )

                _client, runtime, request = self.start(td, script)
                runtime.process_request(request)
                self.assertEqual(
                    self.task(runtime)["commitment"]["plan_resolutions"], []
                )
                self.assertEqual(self.task(runtime)["status"], "committed")

    def test_ordinary_agent_final_still_cannot_close_stale_plan(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(
                td, lambda b, n: self.script(b, n) if n == 1 else msg("Finished")
            )
            with self.assertRaisesRegex(JvError, "COMPLETION-BUDGET"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 5)

    def test_crash_before_durable_commit_recovers_saved_response_once(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td)
            with (
                patch.object(runtime.processor.state, "commit_task", side_effect=Crash),
                self.assertRaises(Crash),
            ):
                runtime.process_request(request)
            saved = json.loads((Path(td) / "state.json").read_text())
            self.assertEqual(saved["agent"]["tasks"][0]["status"], "active")
            self.assertEqual(len(client.posts), 3)
            resumed = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            resumed.process_request(request)
            self.assertEqual(self.task(resumed)["status"], "committed")
            self.assertEqual(len(client.posts), 3)

    def test_crash_after_commit_before_delivery_redelivers_same_final(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td)
            real = runtime.processor.state.commit_task

            def crash(*args):
                real(*args)
                raise Crash()

            with (
                patch.object(runtime.processor.state, "commit_task", crash),
                self.assertRaises(Crash),
            ):
                runtime.process_request(request)
            saved = json.loads((Path(td) / "state.json").read_text())
            self.assertEqual(saved["agent"]["tasks"][0]["status"], "committed")
            self.assertEqual(saved["agent"]["interactions"][-1]["status"], "final")
            resumed = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            final = resumed.process_request(request)
            self.assertEqual(final, resumed.process_request(request))
            self.assertEqual(final[0], saved["agent"]["interactions"][-1]["output"])
            self.assertEqual(len(client.posts), 3)

    def test_failed_or_uncertain_atomic_write_never_writes_partial_commit(self):
        for after in (False, True):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as td:
                client, runtime, request = self.start(td)
                state = runtime.processor.state
                original = state._write

                def fail(state=state, after=after, original=original):
                    if state.value["agent"]["tasks"][-1]["status"] == "committed":
                        if after:
                            original()
                        raise JvError("synthetic disk failure")
                    original()

                with (
                    patch.object(state, "_write", fail),
                    self.assertRaisesRegex(JvError, "disk failure"),
                ):
                    runtime.process_request(request)
                self.assertTrue(state.write_failed)
                with self.assertRaisesRegex(JvError, "PERSISTENCE"):
                    runtime.process_request(request)
                disk = json.loads((Path(td) / "state.json").read_text())
                self.assertEqual(
                    disk["agent"]["tasks"][-1]["status"],
                    "committed" if after else "active",
                )
                resumed = AdapterRuntime(
                    client, processor=AgentProcessor(client, Path(td))
                )
                resumed.process_request(request)
                self.assertEqual(self.task(resumed)["status"], "committed")
                self.assertEqual(len(client.posts), 3)

    def test_corrupt_reconciliation_refused_on_restart(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td)
            runtime.process_request(request)
            path = Path(td) / "state.json"
            saved = json.loads(path.read_text())
            saved["agent"]["tasks"][0]["plan_reconciliation"]["resolutions"][0][
                "resolution"
            ] = "invented"
            path.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ProtocolError, "INTEGRITY"):
                AgentProcessor(client, Path(td))

    def test_042_journal_fails_closed_without_rewriting(self):
        with tempfile.TemporaryDirectory() as td:
            client, _runtime, _request = self.start(td)
            path = Path(td) / "state.json"
            saved = json.loads(path.read_text())
            saved["agent"]["version"] = 1
            saved["agent_integrity"] = _digest(
                {k: v for k, v in saved.items() if k != "agent_integrity"}
            )
            path.write_text(json.dumps(saved))
            before = path.read_bytes()
            with self.assertRaisesRegex(ProtocolError, "fresh .*current JV CLI version"):
                AgentProcessor(client, Path(td))
            self.assertEqual(path.read_bytes(), before)

    def test_second_user_turn_after_reconciled_completion(self):
        def script(body, n):
            if n <= 3:
                return self.script(body, n)
            self.assertFalse(context(body)["completion_review"])
            self.assertEqual(context(body)["plan"], [])
            return msg("Welcome")

        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td, script)
            final = runtime.process_request(request)[0]
            request["input"].extend([final, {"role": "user", "content": "Thank you"}])
            resumed = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            self.assertEqual(
                resumed.process_request(request)[0]["content"][0]["text"], "Welcome"
            )
            self.assertEqual(len(client.posts), 4)

    def test_plan_ids_bind_order_duplicate_text_and_source_call(self):
        def script(body, n):
            if n in (1, 2):
                return tool(
                    json.dumps({"plan": [PLAN[0], PLAN[0]]}), name="update_plan"
                )
            return msg("candidate") if n == 3 else msg(json.dumps(resolved(body)))

        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td, script)
            call = runtime.process_request(request)[0]
            first = context(client.posts[-1][0])["plan"]
            self.result(request, call, "Plan updated")
            runtime.process_request(request)
            second = self.task(runtime)["plan_reconciliation"]["plan_before"]
            self.assertEqual(len({s["step_id"] for s in first + second}), 4)

    def test_plan_and_commitment_size_limits(self):
        for plan in ([PLAN[0]] * 65, [{"step": "x" * 16384, "status": "pending"}]):
            with tempfile.TemporaryDirectory() as td:
                _client, runtime, request = self.start(
                    td,
                    lambda b, n, plan=plan: tool(
                        json.dumps({"plan": plan}), name="update_plan"
                    ),
                )
                with self.assertRaisesRegex(ProtocolError, "PLAN-BUDGET"):
                    runtime.process_request(request)

        def oversized(body, n):
            if n < 3:
                return self.script(body, n)
            value = resolved(body)
            value["artifacts"] = "x" * 16384
            return msg(json.dumps(value))

        with tempfile.TemporaryDirectory() as td:
            client, runtime, request = self.start(td, oversized)
            with self.assertRaisesRegex(ProtocolError, "COMPLETION-SIZE"):
                runtime.process_request(request)
            self.assertNotIn("plan_reconciliation", self.task(runtime))
            self.assertEqual(len(client.posts), 3)
