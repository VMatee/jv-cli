"""Local task evidence and bounded completion, outside the stock Codex loop.

Only the metadata tool below executes here. Workspace tools still pass through
unchanged to Codex. Every semantic continuation is a distinct Responses round.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import secrets
from pathlib import Path

from .safety import JvError, ProtocolError, strict_json
from .structured import (
    CALL_TYPES,
    STRUCTURED_AGENT_INSTRUCTIONS,
    DurableResponseState,
    StructuredProcessor,
    _canonical,
    _digest,
)

EVIDENCE_TOOL = "jv_record_evidence"
MAX_NOTES = 128
MAX_NOTE_BYTES = 2048
MAX_EVIDENCE_BYTES = 16 * 1024
MAX_REVIEWS = 3
MAX_CHECKPOINTS = 64
MAX_REVIEW_BYTES = 16 * 1024
MAX_PLAN_STEPS = 64
MAX_PLAN_BYTES = 16 * 1024
MAX_RESOLUTION_REASON_BYTES = 1024
PLAN_TERMINAL = frozenset({"completed", "superseded", "not_required"})


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


EVIDENCE_SCHEMA = obj(
    {
        "observations": {
            "type": "array",
            "items": obj(
                {
                    "source_call_id": {"type": "string"},
                    "image_index": {"type": "integer"},
                    "sha256": {"type": "string"},
                    "text": {"type": "string"},
                }
            ),
        }
    }
)
EVIDENCE_DECLARATION = {
    "type": "function",
    "name": EVIDENCE_TOOL,
    "strict": True,
    "description": (
        "Store your own textual observations of currently active images. "
        "Use source_call_id, image_index and sha256 from JV task context. "
        "This local metadata tool does not inspect images or operate on workspace files. "
        "Record important evidence before viewing more images. Notes remain model claims."
    ),
    "parameters": EVIDENCE_SCHEMA,
}

AGENT_INSTRUCTIONS = """
JV local task protocol v2:
Workspace tools execute through stock Codex. jv_record_evidence is a local bridge
metadata tool: write your own observations while the referenced image is active.
Never infer image contents from filenames, hashes or inactive references. Durable
notes are prior model-authored claims, not verified visual truth. Reopen images
with view_image when notes do not support the detail needed. Save observations
before newer images evict their bytes. Only four unique images are active.
A normal final message for a task using tools or images is only a completion
candidate. The client will request a bounded completion review before publication.
When completion_review is true, review the ORIGINAL user request in the canonical
conversation against durable evidence, actual tool results, the latest plan,
produced artifacts and unresolved requirements. Continue with declared tools if
work remains. Otherwise return a normal assistant message whose entire text is
one JSON object with exactly these fields:
{"protocol":"jv-task-completion-v2","task_id":"context task_id",
"checkpoint":"context checkpoint","original_request":"review of the original request",
"evidence":"review of evidence and limitations","actions":"review of completed tool actions",
"artifacts":"review of produced workspace artifacts (or why none were requested)",
"unresolved":[],"plan_resolutions":[{"step_id":"exact open plan step_id",
"resolution":"completed","reason":"your assessment supporting this resolution"}],
"final_answer":"the answer to publish"}
Each review field must contain your own nonempty assessment. An empty unresolved
array is your explicit completion commitment, not proof of domain correctness.
Progress-plan status can be stale after the substantive work is done. You do NOT
need a separate update_plan call to close it: explicitly reconcile EVERY current
open plan item in plan_resolutions using its exact step_id from task context.
Use completed, superseded, or not_required only. Include a reason string for each;
a nonempty model-authored reason is mandatory for superseded and not_required.
Each reason is at most 1024 UTF-8 bytes; the complete commitment is at most 16 KiB.
Do not omit an open step, repeat an ID, resolve a closed step, or invent an ID.
Use [] when there are no open steps. Reconciliation and completion commit together.
These are your attestations, not client verification of domain truth. Superseded
or not_required must explain why the original user request is still satisfied;
they cannot dismiss genuinely unfinished requirements. If work remains, keep it
in unresolved and continue with tools. Do not claim completion with unverified
promised files. An ordinary final message does not commit completion.
Do not put this commitment inside a code fence. It is the text of your protocol
message, not a replacement for the outer provider response envelope.
"""


class AgentState(DurableResponseState):
    """Atomic state and corruption detection; the same OS user is the trust boundary."""

    def __init__(self, directory):
        super().__init__(directory)
        saved = self.value.get("agent_integrity")
        if saved is not None:
            unsigned = {k: v for k, v in self.value.items() if k != "agent_integrity"}
            if saved != _digest(unsigned):
                raise ProtocolError("JV-AGENT-INTEGRITY: task journal changed")
        elif self.rounds or "agent" in self.value:
            raise ProtocolError(
                "JV-AGENT-LEGACY-STATE: preserve the old session; start a fresh 0.4.3 task"
            )
        self.value.setdefault(
            "agent",
            {
                "version": 2,
                "session_id": "session_" + secrets.token_hex(16),
                "tasks": [],
                "interactions": [],
                "hidden": [],
            },
        )
        if self.value["agent"].get("version") != 2:
            raise ProtocolError(
                "JV-AGENT-LEGACY-STATE: preserve this journal; start a fresh 0.4.3 session"
            )

    def prepare(self, *args, **kwargs):
        index = super().prepare(*args, **kwargs)
        self.update(
            index, logical_purpose=getattr(self, "round_purpose", "agent_inference")
        )
        return index

    def _write(self):
        self.value["agent_integrity"] = _digest(
            {k: v for k, v in self.value.items() if k != "agent_integrity"}
        )
        super()._write()

    def commit_task(self, task, interaction, final):
        """One durable replacement: reconciled plan, commitment and final delivery record.

        A failed/uncertain write poisons this instance. A new instance reads either
        the old state (revalidate the saved model response) or the complete new
        state (redeliver the same final ID). Never perform a compensating write.
        """
        previous = self.value
        committed = copy.deepcopy(previous)
        for index, current in enumerate(committed["agent"]["tasks"]):
            if current["task_id"] == task["task_id"]:
                committed["agent"]["tasks"][index] = copy.deepcopy(task)
                break
        else:
            raise ProtocolError("JV-AGENT-COMPLETION-INTEGRITY: unknown task")
        for current in committed["agent"]["interactions"]:
            if current["digest"] == interaction["digest"]:
                if current["status"] != "working":
                    raise ProtocolError(
                        "JV-AGENT-COMPLETION-INTEGRITY: interaction closed"
                    )
                current.update(status="final", output=copy.deepcopy(final))
                break
        else:
            raise ProtocolError("JV-AGENT-COMPLETION-INTEGRITY: unknown interaction")
        self.value = committed
        try:
            self._write()
        except BaseException:
            self.value = previous
            self.write_failed = True
            raise


class AgentProcessor(StructuredProcessor):
    """Gate publication locally, using the existing durable transport unmodified."""

    def __init__(self, client, state_dir: Path):
        self.client = client
        self.state = AgentState(state_dir)
        self.stage = None
        self.last_completion = None

    def begin_turn(self):
        self.last_completion = None

    @staticmethod
    def _tools(request):
        tools, schemas = StructuredProcessor._tools(request)
        if any(t.get("name") == EVIDENCE_TOOL for t in request.get("tools", [])):
            raise ProtocolError("Reserved JV metadata tool name in engine catalog")
        if request.get("tool_choice", "auto") != "none":
            tools = tools + [copy.deepcopy(EVIDENCE_DECLARATION)]
            schemas[EVIDENCE_TOOL] = EVIDENCE_SCHEMA
        return tools, schemas

    def _base_body(self, request, tools):
        body = super()._base_body(request, tools)
        if self.stage and self.stage.get("previous"):
            body["previous_response_id"] = self.stage["previous"]
            body["input"] = self.stage.get("input_override") or [
                {"role": "developer", "content": self.stage["review_notice"]}
            ]
        return body

    def _augmented(self, request, stage):
        result = copy.deepcopy(request)
        inputs = result.get("input", [])
        if isinstance(inputs, str):
            inputs = [{"role": "user", "content": inputs}]
        result["input"] = inputs + copy.deepcopy(
            self.state.value["agent"]["hidden"][: stage["hidden_count"]]
        )
        result["instructions"] = stage["instructions"]
        if stage.get("previous"):
            result["instructions"] = (
                "JV continuation identity: "
                + stage["previous"]
                + "\n"
                + result["instructions"]
            )
        return result

    def _observations(self, request, task):
        calls, outputs = self._history(request)
        seen = {(v["source_call_id"], v["image_index"]) for v in task["observations"]}
        groups = []
        inputs = request.get("input", [])
        if isinstance(inputs, list):
            for i, item in enumerate(inputs):
                if item.get("role") == "user" and isinstance(item.get("content"), list):
                    groups.append((f"initial_{i}", None, item["content"]))
        for call_id, output in outputs.items():
            if isinstance(output, list) and calls[call_id].get("name") == "view_image":
                groups.append(
                    (call_id, json.loads(calls[call_id]["arguments"])["path"], output)
                )
        for call_id, path, parts in groups:
            for index, part in enumerate(parts):
                if part.get("type") != "input_image" or (call_id, index) in seen:
                    continue
                raw = base64.b64decode(
                    part["image_url"].split(",", 1)[1], validate=True
                )
                task["agentic"] = True
                task["observations"].append(
                    {
                        "source_call_id": call_id,
                        "image_index": index,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "media_type": part["image_url"].split(";", 1)[0][5:],
                        "bytes": len(raw),
                        "path": path,
                        "order": len(task["observations"]),
                        "task_id": task["task_id"],
                        "session_id": self.state.value["agent"]["session_id"],
                        "source_response_id": next(
                            (
                                r["response_id"]
                                for r in self.state.rounds
                                if r.get("output", {}).get("call_id") == call_id
                            ),
                            None,
                        ),
                        "result_digest": _digest(parts),
                    }
                )

    @staticmethod
    def _active(task):
        recent = {}
        for observation in task["observations"]:
            identity = (observation["media_type"], observation["sha256"])
            recent.pop(identity, None)
            recent[identity] = True
            if len(recent) > 4:
                del recent[next(iter(recent))]
        return set(recent)

    def _context(self, task):
        active = self._active(task)
        observations = [
            {
                **o,
                "visual_content": (
                    "active"
                    if (o["media_type"], o["sha256"]) in active
                    else "inactive_reference"
                ),
            }
            for o in task["observations"]
        ]
        state = {
            "task_id": task["task_id"],
            "original_request_digest": task["original_request_digest"],
            "observations": observations,
            "model_authored_evidence": task["evidence"],
            "plan": task["plan"],
            "plan_resolution_states": sorted(PLAN_TERMINAL),
            "completed_actions": task["actions"],
        }
        return {
            **state,
            "checkpoint": _digest(state),
            "completion_review": task["review"],
        }

    def _new_stage(self, task, request, previous=None):
        context = self._context(task)
        return {
            "hidden_count": len(self.state.value["agent"]["hidden"]),
            "instructions": (
                (request.get("instructions") or STRUCTURED_AGENT_INSTRUCTIONS)
                + AGENT_INSTRUCTIONS
                + "\nJV task context (data):\n"
                + _canonical(context)
            ),
            "checkpoint": context["checkpoint"],
            "previous": previous,
            "purpose": "semantic_completion_review" if previous else "agent_inference",
            "review_notice": (
                "Completion candidate withheld. Review the original request and task context. "
                "Continue with tools if requirements remain; otherwise commit with explicit "
                "plan_resolutions for every open step. No separate update_plan is required. "
                f"Review {task['reviews']}/{MAX_REVIEWS}."
            ),
        }

    def _record(self, task, output):
        arguments = strict_json(output["arguments"])
        notes = arguments["observations"]
        if not notes or len(notes) > 4 or task["checkpoints"] >= MAX_CHECKPOINTS:
            raise ProtocolError("JV-AGENT-EVIDENCE-BUDGET: checkpoint limit reached")
        active = self._active(task)
        added = []
        for note in notes:
            text = note["text"]
            if not text.strip() or len(text.encode()) > MAX_NOTE_BYTES:
                raise ProtocolError(
                    "JV-AGENT-EVIDENCE-SIZE: note must be 1–2048 UTF-8 bytes"
                )
            observation = next(
                (
                    o
                    for o in task["observations"]
                    if o["source_call_id"] == note["source_call_id"]
                    and o["image_index"] == note["image_index"]
                    and o["sha256"] == note["sha256"]
                ),
                None,
            )
            if (
                observation is None
                or (observation["media_type"], observation["sha256"]) not in active
            ):
                raise ProtocolError(
                    "JV-AGENT-EVIDENCE-SOURCE: observation is unknown or inactive"
                )
            added.append(
                {
                    "authorship": "model",
                    "observation": copy.deepcopy(observation),
                    "text": text,
                    "evidence_call_id": output["call_id"],
                    "order": len(task["evidence"]) + len(added),
                }
            )
        combined = task["evidence"] + added
        if (
            len(combined) > MAX_NOTES
            or len(_canonical(combined).encode()) > MAX_EVIDENCE_BYTES
        ):
            raise ProtocolError(
                "JV-AGENT-EVIDENCE-BUDGET: durable evidence memory exhausted"
            )
        task["agentic"] = True
        task["evidence"] = combined
        task["checkpoints"] += 1
        return _canonical({"protocol": "jv-model-evidence-v1", "accepted": added})

    def _commit(self, task, output, checkpoint):
        try:
            value = strict_json(output["content"][0]["text"])
        except (ValueError, UnicodeError, RecursionError):
            return None
        fields = {
            "protocol",
            "task_id",
            "checkpoint",
            "original_request",
            "evidence",
            "actions",
            "artifacts",
            "unresolved",
            "plan_resolutions",
            "final_answer",
        }
        if not isinstance(value, dict) or set(value) != fields:
            return None
        if (
            value["protocol"] != "jv-task-completion-v2"
            or value["task_id"] != task["task_id"]
            or value["checkpoint"] != checkpoint
            or self._context(task)["checkpoint"] != checkpoint
        ):
            raise ProtocolError(
                "JV-AGENT-COMPLETION-INTEGRITY: commitment does not match the current task checkpoint"
            )
        if value["unresolved"] != []:
            return None
        if any(
            not isinstance(value[k], str) or not value[k].strip()
            for k in (
                "original_request",
                "evidence",
                "actions",
                "artifacts",
                "final_answer",
            )
        ):
            return None
        if len(_canonical(value).encode()) > MAX_REVIEW_BYTES:
            raise ProtocolError("JV-AGENT-COMPLETION-SIZE: commitment exceeds 16 KiB")
        resolutions = value["plan_resolutions"]
        if not isinstance(resolutions, list) or len(resolutions) > MAX_PLAN_STEPS:
            raise ProtocolError("JV-AGENT-PLAN-RESOLUTION: expected bounded list")
        opened = {
            s["step_id"]: s for s in task["plan"] if s["status"] not in PLAN_TERMINAL
        }
        accepted = {}
        for resolution in resolutions:
            if not isinstance(resolution, dict) or set(resolution) != {
                "step_id",
                "resolution",
                "reason",
            }:
                raise ProtocolError("JV-AGENT-PLAN-RESOLUTION: invalid fields")
            step_id = resolution["step_id"]
            state = resolution["resolution"]
            reason = resolution["reason"]
            if (
                not isinstance(step_id, str)
                or step_id not in opened
                or step_id in accepted
                or not isinstance(state, str)
                or state not in PLAN_TERMINAL
                or not isinstance(reason, str)
                or len(reason.encode("utf-8")) > MAX_RESOLUTION_REASON_BYTES
                or (state != "completed" and not reason.strip())
            ):
                raise ProtocolError(
                    "JV-AGENT-PLAN-RESOLUTION: unknown, duplicate or invalid resolution"
                )
            accepted[step_id] = resolution
        if set(accepted) != set(opened):
            raise ProtocolError(
                "JV-AGENT-PLAN-RESOLUTION: every open step requires explicit resolution"
            )
        # Tool publications must have canonical client results before completion.
        if any(
            r["phase"] in {"prepared", "submitted", "published"}
            for r in self.state.rounds
        ):
            raise ProtocolError("JV-AGENT-UNRESOLVED: execution remains unreconciled")
        completed = copy.deepcopy(task)
        completed["plan_reconciliation"] = {
            "authorship": "model",
            "plan_before": copy.deepcopy(task["plan"]),
            "checkpoint": checkpoint,
            "resolutions": copy.deepcopy(resolutions),
        }
        for step in completed["plan"]:
            if step["step_id"] in accepted:
                resolution = accepted[step["step_id"]]
                step.update(
                    status=resolution["resolution"],
                    resolution_reason=resolution["reason"],
                )
        completed["commitment"] = value
        completed["status"] = "committed"
        return completed, {
            **output,
            "content": [
                {
                    "type": "output_text",
                    "text": value["final_answer"],
                    "annotations": [],
                }
            ],
        }

    def infer(self, request, runtime):
        if self.state.write_failed:
            raise JvError(
                "JV-AGENT-PERSISTENCE: stop and reconcile failed task persistence"
            )
        self._validate_local_request(request)
        # Complete validation remains in the transport. Nothing here reads image
        # paths or interprets image content; descriptors derive only from validated bytes.
        from .images import validate_image_history

        validate_image_history(request.get("input", []))
        agent = self.state.value["agent"]
        external_digest = _digest(
            {
                k: request.get(k)
                for k in ("instructions", "input", "tools", "tool_choice")
            }
        )
        interaction = next(
            (
                i
                for i in reversed(agent["interactions"])
                if i["digest"] == external_digest
            ),
            None,
        )
        if interaction is None:
            if any(i["status"] == "working" for i in agent["interactions"]):
                raise ProtocolError(
                    "JV-AGENT-UNRESOLVED: resume the exact outstanding local request"
                )
            merged = copy.deepcopy(request)
            if isinstance(merged.get("input"), str):
                merged["input"] = [{"role": "user", "content": merged["input"]}]
            merged["input"] = merged.get("input", []) + agent["hidden"]
            parent, result = self._verify_history(merged)
            previous_task = agent["tasks"][-1] if agent["tasks"] else None
            messages = [m for m in self._messages(request) if m["role"] != "assistant"]
            message_digests = [_digest(m) for m in messages]
            successor_input = None
            successor_response = None
            if parent is None:
                if previous_task:
                    old = previous_task["message_digests"]
                    if (
                        previous_task["status"]
                        not in ("committed", "conversation_complete")
                        or message_digests[: len(old)] != old
                        or len(message_digests) <= len(old)
                    ):
                        raise ProtocolError(
                            "JV-AGENT-HISTORY: task history changed or lost its original request; preserve the session"
                        )
                    successor_input = messages[len(old) :]
                    successor_response = self.state.rounds[-1]["response_id"]
                task_id = "task_" + external_digest[:32]
                task = {
                    "task_id": task_id,
                    "original_request_digest": _digest(successor_input or messages),
                    "status": "active",
                    "agentic": False,
                    "observations": [],
                    "evidence": [],
                    "actions": [],
                    "plan": [],
                    "review": False,
                    "reviews": 0,
                    "checkpoints": 0,
                    "round_limit": runtime.max_requests,
                    "logical_rounds": [],
                    "message_digests": message_digests,
                }
                if previous_task:
                    task["observations"] = copy.deepcopy(previous_task["observations"])
                    task["evidence"] = copy.deepcopy(previous_task["evidence"])
                agent["tasks"].append(task)
            else:
                task = agent["tasks"][-1]
                task["agentic"] = True
                call = self.state.rounds[parent]["output"]
                task["actions"].append(
                    {
                        "call_id": call["call_id"],
                        "name": call["name"],
                        "result_digest": _digest(result),
                    }
                )
                if call["name"] == "update_plan":
                    plan = strict_json(call["arguments"])["plan"]
                    if (
                        len(plan) > MAX_PLAN_STEPS
                        or len(_canonical(plan).encode()) > MAX_PLAN_BYTES
                    ):
                        raise ProtocolError(
                            "JV-AGENT-PLAN-BUDGET: progress plan exceeds bounded memory"
                        )
                    task["plan"] = [
                        {
                            **step,
                            "step_id": "step_"
                            + _digest([task["task_id"], call["call_id"], index, step]),
                            "source_call_id": call["call_id"],
                        }
                        for index, step in enumerate(plan)
                    ]
            if parent is not None and message_digests != task["message_digests"]:
                raise ProtocolError(
                    "JV-AGENT-HISTORY: original request changed during an active task"
                )
            self._observations(merged, task)
            interaction = {
                "digest": external_digest,
                "task_id": task["task_id"],
                "status": "working",
                "stage": self._new_stage(task, request),
            }
            if successor_input is not None:
                interaction["stage"]["previous"] = successor_response
                interaction["stage"]["input_override"] = successor_input
            agent["interactions"].append(interaction)
            self.state._write()
        else:
            task = next(
                t for t in agent["tasks"] if t["task_id"] == interaction["task_id"]
            )
            if interaction["status"] == "published":
                raise ProtocolError(
                    "Refusing to publish the same structured tool call twice; reconcile its local side effect"
                )
            if interaction["status"] == "failed":
                raise JvError(interaction["error"])
            if interaction["status"] == "final":
                # Repeated HTTP delivery is the same publication, never a new round.
                self.last_completion = task["status"]
                return [copy.deepcopy(interaction["output"])]
        try:
            while True:
                self.stage = interaction["stage"]
                self.state.round_purpose = self.stage["purpose"]
                augmented = self._augmented(request, self.stage)
                digest = _digest(
                    {
                        k: augmented.get(k)
                        for k in ("instructions", "input", "tools", "tool_choice")
                    }
                )
                match = self.state.matching(digest)
                if digest not in task["logical_rounds"]:
                    if len(task["logical_rounds"]) >= task["round_limit"]:
                        raise JvError(
                            "JV-AGENT-ROUND-BUDGET: Model-request limit reached for this task"
                        )
                    task["logical_rounds"].append(digest)
                    self.state._write()
                if (
                    match
                    and match[1]["phase"] == "published"
                    and match[1].get("output", {}).get("name") == EVIDENCE_TOOL
                ):
                    # Crash after metadata call receipt but before atomic local commit.
                    # Reconciliation performs no workspace side effect or inference.
                    output = match[1]["output"]
                else:
                    output = super().infer(augmented, runtime)[0]
                if output.get("name") == EVIDENCE_TOOL:
                    result = self._record(task, output)
                    agent["hidden"].extend(
                        [
                            copy.deepcopy(output),
                            {
                                "type": "function_call_output",
                                "call_id": output["call_id"],
                                "output": result,
                            },
                        ]
                    )
                    interaction["stage"] = self._new_stage(task, request)
                    interaction["stage"]["purpose"] = "evidence_continuation"
                    self.state._write()
                    continue
                if output["type"] in CALL_TYPES:
                    interaction.update(status="published", output=output)
                    self.state._write()
                    return [copy.deepcopy(output)]
                nontrivial = task["agentic"]
                if not nontrivial:
                    task["status"] = "conversation_complete"
                    final = output
                else:
                    committed = (
                        self._commit(task, output, self.stage["checkpoint"])
                        if task["review"]
                        else None
                    )
                    if committed is not None:
                        completed, final = committed
                        self.state.commit_task(completed, interaction, final)
                        self.last_completion = "committed"
                        return [copy.deepcopy(final)]
                    if committed is None:
                        if task["reviews"] >= MAX_REVIEWS:
                            raise JvError(
                                "JV-AGENT-COMPLETION-BUDGET: task completion was not committed after 3 reviews"
                            )
                        task["review"] = True
                        task["reviews"] += 1
                        interaction["stage"] = self._new_stage(
                            task, request, runtime.last_response_id
                        )
                        self.state._write()
                        runtime.notices.put(
                            "Reviewing task completion before publishing the final answer"
                        )
                        continue
                interaction.update(status="final", output=final)
                self.last_completion = task["status"]
                self.state._write()
                return [copy.deepcopy(final)]
        except JvError as exc:
            # Ambiguous transport outcomes retain the exact prepared stage/key.
            from .safety import SubmissionUncertain

            if (
                not self.state.write_failed
                and not isinstance(exc, SubmissionUncertain)
                and not runtime.cancel.is_set()
            ):
                interaction.update(status="failed", error=str(exc))
                self.state._write()
            raise
        finally:
            self.stage = None
