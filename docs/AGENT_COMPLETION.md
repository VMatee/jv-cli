# JVCLI 0.4.3 completion and plan reconciliation

Status: canonical 0.4.3 architecture with production Scenario 01 acceptance on
2026-09-12. GitHub publication remains a separate release gate. This document
describes structured mode (`JVCLI_AGENT_API=1`). The legacy jobs adapter remains
available with its existing behavior and frozen compatibility contracts.

## Failure and boundaries

The final 0.4.2 acceptance session `20260910T045103Z-00138f85bdd0`
processed six pages with correct visual eviction, committed six model-authored
notes and created the requested reports. The model left its progress plan open,
acknowledged that blocker in two attempted commitments, then returned prose.
Three completion reviews exhausted and the CLI correctly exited 1. The missing
capability was a structural way to reconcile stale progress metadata inside the
completion commitment. Visual context and evidence were not the defect.

0.4.3 adds that capability without relaxing the completion gate. `update_plan`
remains the stock progress tool; its model-authored status is advisory metadata.
Completion authority is a task-bound model attestation with explicit resolution
of every currently open step. Neither file existence nor an ordinary final answer
can silently close a plan. Production acceptance does not weaken that completion
gate.

The implementation separates five boundaries:

| Boundary | Authority and meaning |
| --- | --- |
| Provider/protocol | Central validates one complete typed response; transport success says nothing about task completion. |
| Tool execution | Stock Codex executes workspace tools under its sandbox. Actual returned results, including failures, are canonical evidence of execution. |
| Durable task evidence | The model authors notes; the local bridge validates and journals associations. Central preserves the original call/result pair. |
| Active context | Central selects at most four recent unique visual binaries and compiles historical references. |
| Semantic completion | The local bridge requires an explicit, bounded, model-authored completion commitment for a task that used tools or images. |

`lib/jvcli/structured.py` remains the low-level Responses transport and validation
implementation. `lib/jvcli/agent.py` adds task orchestration; normal structured
CLI execution constructs `AgentProcessor`. The transport-only class remains
useful for independent wire-contract regression tests. There is no runtime flag
to bypass task completion in the structured CLI.

## Stock Codex decision

The embedded npm engine stays exactly `@openai/codex@0.149.1`. Neither its package
nor source is modified. Inspection of tag `rust-v0.149.1` established:

* `codex-rs/core/src/session/turn.rs` derives follow-up from tool handling/pending
  input; when no follow-up is needed it proceeds to stop hooks and turn completion.
* The `ResponseEvent::Completed` handler can set follow-up for `end_turn:false`.
  That is a loop signal, not a durable semantic completion attestation.
* Task/turn-complete events consumed by `exec` describe engine turn lifecycle.
  An ordinary assistant response can satisfy that lifecycle without finishing
  the user task. `tool_choice:auto` permits that response.
* `view_image` uses the stock filesystem/sandbox context for metadata and reading.
  Its output enters stock history, including raw image content on later replay.
* Compaction in `core/src/compact.rs` replaces internal history through
  `Session::replace_compacted_history`; the bridge has no transactional handle
  for replacing that history together with its tool journal.

Source reference: https://github.com/openai/codex/tree/rust-v0.149.1/codex-rs
The downloaded inspection file hashes are retained in the overnight audit.
Actual pinned-binary captures remain the compatibility gate where optional
features/source schemas differ from the tools enabled by the wrapper.

The chosen mechanism is a bounded local completion-review inference. Workspace
tool calls cross the bridge unchanged. Internal metadata calls are handled by
the local wrapper and paired with ordinary function results in the Server's
canonical continuation. Stock Codex receives only its own declared tools or an
accepted final message. Its request stream can remain open while the bridge runs
a bounded internal continuation; existing cancellation and turn deadlines apply.

Alternatives rejected: changing provider prompts, increasing the visual window,
patching Codex, inventing image summaries, publishing a bogus workspace tool to
force a loop, and treating `end_turn:false` alone as completion. An MCP subprocess
would add an independently mutable state owner without solving publication
admission. A `complete_task` tool followed by another inference would leave an
extra remote tool/result boundary; the reviewed assistant commitment gives a
fully terminal canonical response and an atomic local publication checkpoint.

## Canonical observations and model-authored evidence

The local-only metadata tool `jv_record_evidence` accepts one to four observations
per call. Each contains `source_call_id`, `image_index`, `sha256` and the exact
model-authored `text`. These fields are validated against image results that
already passed full local history/call matching and image validation. A note can
be newly committed only while its image content identity is active.

The journal adds provenance without interpreting pixels: task/session identity,
source response/call identity, image index, MIME, byte count, SHA-256, declared
client path where available, observation order, result digest, note order and
evidence-call identity. Initial images have a deterministic initial-input
identity and need not disclose a workspace path. Model text is never synthesized,
OCRed, captioned or rewritten by the bridge or Server.

Notes and the metadata call result are committed atomically in the same private
journal as transport state. The next logical response submits that result through
`previous_response_id`, so the Server canonically retains both the model-authored
arguments and their accepted local result. Central's context compiler checks the
text against the exact model call and checks view-image digest/path associations
before labeling a reference with `model_authored_evidence`. Ordinary shell output
cannot impersonate that metadata call. Initial-image claims remain in their
canonical tool pair and are checked against canonical initial image descriptors.

A note is a prior model claim, not Server-generated truth. Wrong model perception
can produce a wrong note; the model must reopen an image when a note is inadequate.

| Evidence resource | Bound |
| --- | --- |
| Notes per call | 1–4 |
| One note | 2,048 UTF-8 bytes |
| Complete evidence ledger, including provenance | 16 KiB |
| Notes / metadata commits per task | 128 / 64 |
| Whole completion commitment | 16 KiB |
| Whole durable session journal | Existing 64 MiB and 500 logical rounds |

Budgets fail closed with stable `JV-AGENT-EVIDENCE-*` diagnostics. No notes are
silently discarded or condensed. Successor tasks retain prior notes and their
original provenance, within the same bounded session memory.

## Active visual context

`MAX_ACTIVE_CONTEXT_IMAGES` remains **4**. Images are selected by recent
observation order and content identity (kind, MIME, SHA-256). Repeated bytes can
share an attachment; separate observations keep separate call identities.

Canonical image records are immutable. Inactive binary content is absent from
provider attachments. Only the compiled copy gains a factual inactive reference
and, where available, separately labeled model-authored evidence. Attachment
mappings name actual active uploads. No-note prompts remain byte-identical to
the prior accepted compilation, including ordinary text/image requests.

A fresh `view_image` remains a real client tool call. Stock Codex revalidates and
reads the path using its filesystem policy. The bridge validates the returned
bytes and their new call identity; replayed historical paths, calls or results
must match saved state. The original observation is not rewritten if the actual
file changes and is intentionally viewed under a new call. Existing initial-image
snapshot confinement, symlink checks, media validation and native sandbox policy
remain unchanged. This is not a new promise that all readable paths outside the
workspace are inaccessible to the stock engine.

## Completion state machine

A task using no tools or new images may return normal text in one inference.
Inherited evidence alone does not force a new conversational turn into review.
For an agentic task:

1. Any first normal assistant final is stored as a **candidate**, withheld from
   the stock engine and user-facing final output.
2. The bridge freezes a new `semantic_completion_review` stage, a new logical
   Responses round/key, the exact predecessor, and a digest of original intent,
   durable evidence, observations, plan and completed tool-result identities.
3. The model reviews the ORIGINAL request in canonical conversation context. It
   may return any declared tool to continue actual work. Tools/results continue
   through the stock engine and existing exactly-once guards.
4. To finish, the model returns an assistant message whose entire text is a
   strict `jv-task-completion-v2` JSON commitment. It binds `task_id` and current
   `checkpoint`, contains nonempty original-request/evidence/actions/artifact
   reviews, `unresolved:[]`, `plan_resolutions`, and `final_answer`.
5. The bridge validates the exact current checkpoint, complete plan coverage,
   allowed resolutions and bounded reasons. Nonempty unresolved requirements never
   commit. An accepted reconciliation, task commitment and final delivery record
   become durable together in one journal replacement, then the final is returned.

The commitment is structured content inside the already validated assistant
message. Parsing it is not JSON repair: no prefix salvage, fence stripping,
truncation, guessed fields or edits are performed. Ordinary/missing commitments and nonempty unresolved requirements consume
only the explicitly bounded semantic review allowance. A recognized v2 commitment
with invalid plan coverage/fields or stale binding fails with a stable protocol
error, rather than inventing a resolution or hiding additional retries. They never trigger the
provider replacement classifier.

There are at most **3 review requests per task**, also charged to the frozen
normal task budget (40 default; configured maximum 500). After the initial review,
continuing tools can eventually commit without another redundant candidate pass.
Malformed/unresolved finals may request another review, up to that fixed cap.
Round exhaustion and review exhaustion return stable errors and no successful
final. The model may still falsely attest completion; the protocol is not an
objective verifier of arbitrary business answers or artifact correctness.

## Atomic plan reconciliation

Fresh agent journals use schema version **2**. Each reconciled `update_plan` tool
result installs the latest progress plan with deterministic `step_id` values
computed from task identity, source tool call identity, step position and original
step content/status. Repeated text and reordered or replaced plans cannot reuse
an identity accidentally. The actual model call and client result stay unchanged
in canonical history; no fields are injected into the stock tool schema.

A plan is bounded to 64 steps and 16 KiB of original model arguments. A commitment
is still at most 16 KiB in total. Its required `plan_resolutions` list contains
exactly one object for every open step in current task context, and no other IDs:

```json
{
  "step_id": "step_<exact context identity>",
  "resolution": "completed",
  "reason": "Model-authored explanation supporting this resolution"
}
```

Allowed resolutions are `completed`, `superseded`, and `not_required`. `reason`
is always a string, at most 1024 UTF-8 bytes; it must be nonempty for superseded
and not_required. Those states explicitly attest why the original request is
still satisfied; they are not authority to abandon an unfinished requirement.
The client validates syntax and current binding, not the truth of that assertion.
Completed steps need no new resolution; an empty/no explicit plan uses `[]`.
Missing, duplicate, unknown, already-closed or stale IDs fail closed. Nonempty
`unresolved` always prevents commitment even with completed declarations. Truly
unfinished work continues through declared tools within the same review budget.

The checkpoint covers original intent identity, observations, evidence, canonical
plan and reconciled tool results. It is rechecked against current state during
commitment validation, not merely against the digest echoed by the model. A pending
transport/tool publication blocks completion. The accepted record preserves the
entire pre-reconciliation plan, exact model reasons and checkpoint under
`plan_reconciliation`; the current plan receives the explicitly attested terminal
states. No client-generated completion reason or inferred domain fact is added.

Validation builds a detached task copy. `AgentState.commit_task` publishes the
reconciled plan, commitment and final interaction together in one fsynced atomic
journal replacement. Before that replacement a crash leaves the old active plan;
recovery revalidates the already saved model response without another inference.
After replacement a crash leaves the complete committed task and delivery record;
recovery returns the same response/item identity. A persistence exception poisons
the current instance and never triggers a compensating write that could save a
partial transition. Fresh recovery reads either the old or complete new record.
This is exactly-once state transition and stable replay, not a claim of exactly-once
rendering by an arbitrary HTTP consumer without acknowledgement.

Alternatives rejected: ignoring open plans or inferring completion from files
would invent model intent; raising three reviews would hide the liveness issue;
requiring another housekeeping tool recreates the defect; patching Codex or adding
a Server-side local-action executor violates the existing boundary. The deployed
Server preserves that boundary: it validates and carries JV-WIRE-V1 structured
agent transport while client actions remain client-side. Scenario 01 production
acceptance exercised that separation.

## Rounds, attempts and telemetry

Each new inference has a distinct journal round/key and Server response ID.
Journal `logical_purpose` distinguishes `agent_inference`,
`evidence_continuation` and `semantic_completion_review`. Task logical-round
allocation is durable and its configured allowance cannot be raised on resume.

Fresh JV-WIRE-V1 structured jobs use a separate bounded wire-format policy:

```
logical response
  -> generation 1 primary
  -> generations 2-5 only for rejected wire-format candidates
  -> one validated publication; never generation 6
```

Legacy frozen `jv-action-v1` conversations retain their two-attempt
transport/structured-repair compatibility policy; that policy is not stacked on
JV-WIRE-V1. Same-key acknowledgement reconciliation refers to one existing
response. Semantic completion review is a NEW logical response with fresh
canonical continuation. Client tool and safety failures remain ordinary
agent-loop events rather than wire-format retries. None of these paths changes
the frozen provider/model/effort/account assignment, cleanup requirements, or
fallback policy.

## Replay, restart and exactly-once boundaries

One private atomic journal stores transport rounds and task/evidence/interaction
state. It is mode 0600 in private directories, atomically replaced and fsynced
using the existing persistence implementation. A SHA-256 integrity seal detects
changed journal content before restart. It is corruption detection, not a
security boundary against an OS user who can rewrite the journal and its seal.
The OS account/session directory remains the trust boundary.

An exact interrupted request reconstructs its frozen stage and same idempotency
key/body. A received metadata call can be reconciled after a crash without a new
provider request or a workspace side effect. Its note and result are one atomic
commit. Historical returned objects are copied on publication, preventing a
caller from mutating the canonical in-memory journal through an alias.

Published workspace calls are never emitted a second time. If the engine did
not durably return their exact result, the bridge fails closed for reconciliation;
it does not guess whether a shell/patch side effect happened. Completed final
HTTP replays return the same stored publication, with no new inference or
completion transition. CLI turn processing renders one final; no distributed
exactly-once guarantee is claimed for an external consumer replaying HTTP bodies.

A successor user turn retains the same Server conversation using the last
canonical response and only the new user-message suffix. The immutable earlier
user-message prefix is verified. This fixes lossy new-conversation replay at the
wrapper boundary while retaining stock Codex resume behavior and the workspace.
Changed history/compaction or a different request during an unresolved stage
fails closed. Old 0.4.1/0.4.2 agent journals are deliberately refused with
`JV-AGENT-LEGACY-STATE` and an explicit fresh-0.4.3-session instruction. The loader
does not rewrite them. Even old committed journals require a fresh session because
v1 plan identities and reconciliation provenance do not exist; no migration guesses
are made. Fresh v2 sessions resume normally, including after evidence and during
completion review. A committed task may receive a second user turn on its unchanged
canonical Server chain; the successor starts a new progress plan.

## Checkpoint scaling and the 17 MiB limitation

The task checkpoint contains bounded original-request identity, model evidence,
observations, plan, tool-result identities and completion state. It permits more
observations than active binaries; the twenty-image paired test aggregates from
notes without reopening all images. It is not an unlimited scratchpad.

Automatic epoch rollover is **not implemented**. Stock Codex 0.149.1 owns its
rollout, pending local tools, compaction and task-complete lifecycle. The bridge
cannot atomically discard raw image history, replace it with a checkpoint,
advance the Server chain and prove the disposition of in-flight local side
effects. Its internal compaction paths are not an external wrapper transaction.
Forging a rollout or silently starting a new engine would weaken resume integrity.

The incoming structured ceiling remains **17 MiB**. Large historical images can
hit it before task-round limits. The existing 64 KiB request metadata, 16-message
local normalization, Server text/context limit, journal size, file/artifact
expiry and whole-turn deadlines remain independent limits. There is no automatic
summary, cap increase, usage-accounting workaround or hidden epoch reset.

## Exit meaning and verification

For the structured CLI, exit 0 requires the engine's valid completed turn and
final message, no adapter error or unreconciled tool execution, and either a
durably accepted task commitment (including explicit reconciliation of every open
plan step) or a simple conversational completion. A valid transport final by itself cannot make
an agentic turn successful. Interruptions retain exit 130; tool/transport/budget/
completion failures are nonzero. This attests protocol and completion-handshake
state, not objective correctness of domain answers.

The focused offline regression matrix covers the proven fixture-shaped early
termination, evidence association and eviction, twenty observations,
correct/simple finals, review/task budgets, corruption, resume and real Codex
execution. Existing wire, provider-replacement, files/mixed media,
shell/patch/plan, sandbox, network denial, installer, doctor, manifest and parity
checks remain separate gates. `TEST_REPORT.md` records both the offline regression
baseline and the 2026-09-12 Scenario 01 production acceptance, distinguishing
scripted evidence from live evidence.
