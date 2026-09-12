"""Deterministic agent orchestration; no business rules exist in runtime code."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jvcli.adapter import AdapterRuntime
from jvcli.agent import EVIDENCE_TOOL, AgentProcessor
from jvcli.safety import JvError, ProtocolError
from test_structured import FakeStructuredClient, message, response, tool
from test_structured_core import core_request
from test_structured_images import image


def context(body):
    return json.loads(body["instructions"].split("JV task context (data):\n")[-1])


def commitment(body, answer="DONE", unresolved=None):
    ctx = context(body)
    return {
        "protocol": "jv-task-completion-v2",
        "task_id": ctx["task_id"],
        "checkpoint": ctx["checkpoint"],
        "original_request": "Checked original requirements.",
        "evidence": "Checked model evidence and limitations.",
        "actions": "Checked actual tool results.",
        "artifacts": "Verified requested artifacts or none required.",
        "unresolved": [] if unresolved is None else unresolved,
        "plan_resolutions": [],
        "final_answer": answer,
    }


def msg(text):
    item = message()
    item["content"][0]["text"] = text
    return item


class ScriptClient(FakeStructuredClient):
    def __init__(self, script):
        super().__init__([])
        self.script = script

    def create_response(self, body, key):
        self.posts.append((copy.deepcopy(body), key))
        n = len(self.posts)
        output = self.script(body, n)
        output["id"] = f"item_{n}"
        if output["type"] == "function_call":
            output["call_id"] = f"call_{n}"
        return response(output=[output], response_id=f"response_{n}")


class AgentTests(unittest.TestCase):
    def runtime(self, directory, script, **kwargs):
        client = ScriptClient(script)
        return client, AdapterRuntime(
            client, processor=AgentProcessor(client, Path(directory)), **kwargs
        )

    def result(self, request, call, value):
        request["input"].extend(
            [
                call,
                {
                    "type": call["type"] + "_output",
                    "call_id": call["call_id"],
                    "output": value,
                },
            ]
        )

    def test_simple_conversation_is_one_round(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, lambda b, n: msg("Hello"))
            self.assertEqual(
                runtime.process_request(core_request())[0]["content"][0]["text"],
                "Hello",
            )
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(runtime.processor.last_completion, "conversation_complete")

    def test_premature_final_then_tools_and_commit(self):
        def script(b, n):
            if n in (1, 3):
                return tool('{"command":"prepare artifact"}')
            if n == 2:
                return msg("I stopped before making the requested artifact.")
            return msg(json.dumps(commitment(b)))

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            call = runtime.process_request(request)[0]
            self.result(request, call, "not yet done")
            followup = runtime.process_request(request)[0]
            self.assertEqual(followup["type"], "function_call")
            self.assertEqual(client.posts[2][0]["previous_response_id"], "response_2")
            self.assertTrue(context(client.posts[2][0])["completion_review"])
            self.result(request, followup, "artifact done")
            self.assertEqual(
                runtime.process_request(request)[0]["content"][0]["text"], "DONE"
            )
            self.assertEqual(len(client.posts), 4)
            self.assertEqual(runtime.processor.last_completion, "committed")

    def test_correct_final_has_exactly_one_review(self):
        def script(b, n):
            if n == 1:
                return tool()
            return msg("Done") if n == 2 else msg(json.dumps(commitment(b)))

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            call = runtime.process_request(request)[0]
            self.result(request, call, "complete")
            runtime.process_request(request)
            self.assertEqual(len(client.posts), 3)
            again = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            self.assertEqual(
                again.process_request(request)[0]["content"][0]["text"], "DONE"
            )
            self.assertEqual(len(client.posts), 3)

    def test_review_budget_and_task_budget(self):
        for budget in (40, 2):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as td:
                client, runtime = self.runtime(
                    td,
                    lambda b, n: tool() if n == 1 else msg("not finished"),
                    max_requests=budget,
                )
                request = core_request()
                self.result(request, runtime.process_request(request)[0], "unfinished")
                with self.assertRaisesRegex(
                    JvError, "COMPLETION-BUDGET|Model-request limit"
                ):
                    runtime.process_request(request)
                self.assertEqual(len(client.posts), 5 if budget == 40 else 2)

    def test_evidence_and_twenty_observations(self):
        def script(b, n):
            ctx = context(b)
            count = len(ctx["observations"])
            notes = len(ctx["model_authored_evidence"])
            if count > notes:
                o = ctx["observations"][-1]
                return tool(
                    json.dumps(
                        {
                            "observations": [
                                {
                                    "source_call_id": o["source_call_id"],
                                    "image_index": o["image_index"],
                                    "sha256": o["sha256"],
                                    "text": f"Model observed item {count}",
                                }
                            ]
                        }
                    ),
                    name=EVIDENCE_TOOL,
                )
            if count < 20:
                return tool(
                    json.dumps({"path": f"image-{count}.png"}), name="view_image"
                )
            if not ctx["completion_review"]:
                return msg("Aggregation candidate")
            self.assertEqual(notes, 20)
            self.assertEqual(
                sum(o["visual_content"] == "active" for o in ctx["observations"]), 4
            )
            self.assertIn(
                "Model observed item 1", json.dumps(ctx["model_authored_evidence"])
            )
            return msg(json.dumps(commitment(b, "AGGREGATED")))

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script, max_requests=100)
            request = core_request()
            calls = []
            for n in range(20):
                call = runtime.process_request(request)[0]
                calls.append(call["call_id"])
                # Signature-valid synthetic image with distinct bytes; paired tests decode real PNGs.
                part = image()
                import base64

                raw = base64.b64decode(part["image_url"].split(",")[1]) + bytes([n])
                part["image_url"] = (
                    "data:image/png;base64," + base64.b64encode(raw).decode()
                )
                self.result(request, call, [part])
                if n in (4, 10):
                    runtime = AdapterRuntime(
                        client,
                        processor=AgentProcessor(client, Path(td)),
                        max_requests=100,
                    )
            self.assertEqual(
                runtime.process_request(request)[0]["content"][0]["text"], "AGGREGATED"
            )
            self.assertEqual(len(set(calls)), 20)
            self.assertEqual(len(client.posts), 42)
            for body, _ in client.posts:
                active = {
                    o["sha256"]
                    for o in context(body)["observations"]
                    if o["visual_content"] == "active"
                }
                self.assertLessEqual(len(active), 4)
            task = runtime.processor.state.value["agent"]["tasks"][0]
            self.assertEqual(task["evidence"][0]["authorship"], "model")
            self.assertEqual(
                task["evidence"][0]["observation"]["source_call_id"], calls[0]
            )

    def test_journal_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, lambda b, n: msg("Hello"))
            runtime.process_request(core_request())
            path = Path(td) / "state.json"
            original = json.loads(path.read_text())
            for field in ("task_id", "status", "original_request_digest"):
                value = copy.deepcopy(original)
                value["agent"]["tasks"][0][field] = "tampered"
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ProtocolError, "INTEGRITY"):
                    AgentProcessor(client, Path(td))

    def test_wrong_completion_checkpoint_fails_closed(self):
        def script(b, n):
            if n == 1:
                return tool()
            if n == 2:
                return msg("Done")
            value = commitment(b)
            value["checkpoint"] = "wrong"
            return msg(json.dumps(value))

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], "done")
            with self.assertRaisesRegex(ProtocolError, "COMPLETION-INTEGRITY"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 3)


class RecoveryAndSafetyTests(unittest.TestCase):
    runtime = AgentTests.runtime
    result = AgentTests.result

    def test_resume_uncertain_completion_review_uses_same_key_and_body(self):
        from unittest.mock import patch

        from jvcli.safety import SubmissionUncertain

        with tempfile.TemporaryDirectory() as td:

            def script(b, n):
                return tool() if n == 1 else msg("candidate")

            client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], "done")
            original = client.create_response
            attempts = []

            def interrupted(body, key):
                if context(body)["completion_review"]:
                    attempts.append((copy.deepcopy(body), key))
                    raise SubmissionUncertain("synthetic uncertain acknowledgement")
                return original(body, key)

            with (
                patch.object(client, "create_response", interrupted),
                self.assertRaises(SubmissionUncertain),
            ):
                runtime.process_request(request)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])

            def reconciled(body, key):
                self.assertEqual((body, key), attempts[0])
                return response(
                    output=[{**msg(json.dumps(commitment(body))), "id": "commit_item"}],
                    response_id="review_response",
                )

            resumed = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            with patch.object(client, "create_response", reconciled):
                self.assertEqual(
                    resumed.process_request(request)[0]["content"][0]["text"], "DONE"
                )
            self.assertEqual(len(resumed.processor.state.rounds), 3)
            self.assertEqual(
                resumed.processor.state.rounds[-1]["logical_purpose"],
                "semantic_completion_review",
            )

    def test_crash_after_evidence_call_before_commit_does_not_repeat_inference(self):
        from unittest.mock import patch

        def script(b, n):
            if n == 1:
                return tool('{"path":"source.png"}', name="view_image")
            if n == 2:
                o = context(b)["observations"][0]
                return tool(
                    json.dumps(
                        {
                            "observations": [
                                {
                                    "source_call_id": o["source_call_id"],
                                    "image_index": 0,
                                    "sha256": o["sha256"],
                                    "text": "Exact model-authored evidence",
                                }
                            ]
                        }
                    ),
                    name=EVIDENCE_TOOL,
                )
            return msg("candidate") if n == 3 else msg(json.dumps(commitment(b)))

        class Crash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], [image()])
            with (
                patch.object(runtime.processor, "_record", side_effect=Crash),
                self.assertRaises(Crash),
            ):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 2)
            resumed = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            self.assertEqual(
                resumed.process_request(request)[0]["content"][0]["text"], "DONE"
            )
            task = resumed.processor.state.value["agent"]["tasks"][0]
            self.assertEqual(len(task["evidence"]), 1)
            self.assertEqual(
                task["evidence"][0]["text"], "Exact model-authored evidence"
            )
            self.assertEqual(len(client.posts), 4)

    def test_historical_image_path_bytes_and_evidence_association_tampering(self):
        for kind in ("path", "bytes", "source", "digest"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:

                def script(b, n, kind=kind):
                    if n in (1, 2):
                        return tool(
                            json.dumps({"path": f"source-{n}.png"}), name="view_image"
                        )
                    o = context(b)["observations"][0]
                    return tool(
                        json.dumps(
                            {
                                "observations": [
                                    {
                                        "source_call_id": "foreign_call"
                                        if kind == "source"
                                        else o["source_call_id"],
                                        "image_index": 0,
                                        "sha256": "tampered"
                                        if kind == "digest"
                                        else o["sha256"],
                                        "text": "A model claim",
                                    }
                                ]
                            }
                        ),
                        name=EVIDENCE_TOOL,
                    )

                client, runtime = self.runtime(td, script)
                request = core_request()
                self.result(request, runtime.process_request(request)[0], [image()])
                call = runtime.process_request(request)[0]
                self.result(request, call, [image()])
                if kind == "path":
                    request["input"][1]["arguments"] = '{"path":"different.png"}'
                elif kind == "bytes":
                    part = request["input"][2]["output"][0]
                    import base64

                    part["image_url"] = (
                        "data:image/png;base64,"
                        + base64.b64encode(b"\x89PNG\r\n\x1a\nchanged").decode()
                    )
                with self.assertRaises(ProtocolError):
                    runtime.process_request(request)
                self.assertEqual(
                    len(client.posts), 2 if kind in ("path", "bytes") else 3
                )

    def test_outstanding_plan_cannot_commit(self):
        def script(b, n):
            if n == 1:
                return tool(
                    json.dumps(
                        {"plan": [{"step": "unfinished task", "status": "pending"}]}
                    ),
                    name="update_plan",
                )
            return msg("candidate") if n == 2 else msg(json.dumps(commitment(b)))

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], "Plan updated")
            with self.assertRaisesRegex(JvError, "PLAN-RESOLUTION"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 3)

    def test_evidence_byte_budget_and_inactive_source_fail_closed(self):
        def script(b, n):
            if n == 1:
                return tool('{"path":"source.png"}', name="view_image")
            o = context(b)["observations"][0]
            return tool(
                json.dumps(
                    {
                        "observations": [
                            {
                                "source_call_id": o["source_call_id"],
                                "image_index": 0,
                                "sha256": o["sha256"],
                                "text": "x" * 2049,
                            }
                        ]
                    }
                ),
                name=EVIDENCE_TOOL,
            )

        with tempfile.TemporaryDirectory() as td:
            _client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], [image()])
            with self.assertRaisesRegex(ProtocolError, "EVIDENCE-SIZE"):
                runtime.process_request(request)
            self.assertEqual(
                runtime.processor.state.value["agent"]["tasks"][0]["evidence"], []
            )

    def test_normal_round_budget_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(
                td, lambda b, n: tool('{"command":"pwd"}'), max_requests=2
            )
            request = core_request()
            self.result(request, runtime.process_request(request)[0], "first")
            resumed = AdapterRuntime(
                client, processor=AgentProcessor(client, Path(td)), max_requests=100
            )
            self.result(request, resumed.process_request(request)[0], "second")
            resumed = AdapterRuntime(
                client, processor=AgentProcessor(client, Path(td)), max_requests=100
            )
            with self.assertRaisesRegex(JvError, "ROUND-BUDGET"):
                resumed.process_request(request)
            self.assertEqual(len(client.posts), 2)

    def test_engine_zero_exit_without_handshake_is_not_success(self):
        import contextlib
        import io

        from jvcli import cli
        from test_resume_flags import FAKE_ENGINE

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(
                Path(td) / "state", lambda b, n: msg("unused")
            )
            engine = Path(td) / "engine"
            engine.write_text(FAKE_ENGINE)
            engine.chmod(0o755)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code, _ = cli._run_engine(str(engine), "task", None, runtime=runtime)
            self.assertNotEqual(code, 0)
            self.assertIn("JV-AGENT-INCOMPLETE", err.getvalue())
            self.assertEqual(len(client.posts), 0)

    def test_inactive_observation_cannot_gain_a_new_model_note(self):
        def script(b, n):
            if n <= 5:
                return tool(json.dumps({"path": f"page-{n}.png"}), name="view_image")
            o = context(b)["observations"][0]
            return tool(
                json.dumps(
                    {
                        "observations": [
                            {
                                "source_call_id": o["source_call_id"],
                                "image_index": 0,
                                "sha256": o["sha256"],
                                "text": "Cannot see this now",
                            }
                        ]
                    }
                ),
                name=EVIDENCE_TOOL,
            )

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            import base64

            for n in range(5):
                part = image()
                raw = base64.b64decode(part["image_url"].split(",")[1]) + bytes([n])
                part["image_url"] = (
                    "data:image/png;base64," + base64.b64encode(raw).decode()
                )
                self.result(request, runtime.process_request(request)[0], [part])
            with self.assertRaisesRegex(ProtocolError, "EVIDENCE-SOURCE"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 6)
            self.assertEqual(
                runtime.processor.state.value["agent"]["tasks"][0]["evidence"], []
            )

    def test_total_evidence_memory_is_bounded_without_silent_truncation(self):
        def script(b, n):
            if n == 1:
                return tool('{"path":"source.png"}', name="view_image")
            o = context(b)["observations"][0]
            return tool(
                json.dumps(
                    {
                        "observations": [
                            {
                                "source_call_id": o["source_call_id"],
                                "image_index": 0,
                                "sha256": o["sha256"],
                                "text": str(n) + "x" * 2000,
                            }
                        ]
                    }
                ),
                name=EVIDENCE_TOOL,
            )

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], [image()])
            with self.assertRaisesRegex(ProtocolError, "EVIDENCE-BUDGET"):
                runtime.process_request(request)
            evidence = runtime.processor.state.value["agent"]["tasks"][0]["evidence"]
            self.assertGreater(len(evidence), 1)
            self.assertLessEqual(
                len(json.dumps(evidence, separators=(",", ":")).encode()), 16 * 1024
            )
            self.assertTrue(all(len(e["text"]) >= 2001 for e in evidence))
            self.assertLess(len(client.posts), 10)

    def test_changed_original_intent_is_rejected_before_inference(self):
        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, lambda b, n: tool())
            request = core_request()
            self.result(request, runtime.process_request(request)[0], "actual result")
            request["input"][0]["content"][0]["text"] = "substituted user intent"
            with self.assertRaisesRegex(ProtocolError, "JV-AGENT-HISTORY"):
                runtime.process_request(request)
            self.assertEqual(len(client.posts), 1)

    def test_prior_evidence_does_not_burden_a_new_conversational_turn(self):
        def script(b, n):
            if n == 1:
                return tool('{"path":"source.png"}', name="view_image")
            if n == 2:
                return msg("candidate")
            if n == 3:
                return msg(json.dumps(commitment(b)))
            self.assertFalse(context(b)["completion_review"])
            self.assertEqual(b["previous_response_id"], "response_3")
            return msg("You are welcome")

        with tempfile.TemporaryDirectory() as td:
            client, runtime = self.runtime(td, script)
            request = core_request()
            self.result(request, runtime.process_request(request)[0], [image()])
            final = runtime.process_request(request)[0]
            request["input"] += [final, {"role": "user", "content": "Thanks"}]
            resumed = AdapterRuntime(client, processor=AgentProcessor(client, Path(td)))
            self.assertEqual(
                resumed.process_request(request)[0]["content"][0]["text"],
                "You are welcome",
            )
            self.assertEqual(len(client.posts), 4)
            self.assertEqual(resumed.processor.last_completion, "conversation_complete")


if __name__ == "__main__":
    unittest.main()
