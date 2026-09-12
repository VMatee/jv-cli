# Completion architecture audit: 0.4.3

Status: this document preserves the original completion-v2 design audit while
recording the later coordinated production acceptance on 2026-09-12. Historical
offline evidence below retains its original scope.

The final 0.4.2 run completed its substantive artifacts but retained open progress
plan entries. All three reviews lacked the housekeeping update_plan call required
by v1. Refusing commitment was correct; the missing structural path was atomic
model-authored reconciliation of stale progress metadata.

| Audit question | Decision and evidence |
| --- | --- |
| Can completed work finish with a stale plan? | Yes. Every open step is explicitly resolved in a strict v2 commitment. `test_atomic_stale_plan_completion_without_housekeeping_tool`, paired `stale-plan-six`, and real-engine `completion_smoke.py` prove one-review completion. |
| Can unresolved work still not finish? | Declared unresolved requirements or missing client results block commitment. `test_unresolved_requirements_override_resolved_plan_and_exhaust_budget` and `test_missing_tool_result_never_reaches_completion_inference` verify this. The client cannot detect model dishonesty about domain truth. |
| Can an open plan silently disappear at commitment? | No. Exact current step identities are required, with no omissions, duplicates, unknown or closed steps. `test_invalid_resolution_matrix_never_mutates_plan` covers rejection. An earlier explicit update_plan remains model-authored advisory progress metadata. |
| Can the client invent completion? | No. Only the model supplies completed/superseded/not_required resolutions; the latter two require bounded nonempty reasons. No artifact-existence inference is used. |
| Is reconciliation atomic? | Yes. A detached validated task is combined with its final delivery record in one durable state replacement, using the existing fsync/rename journal writer. There is no intermediate persisted completed plan. |
| Can a crash double-commit or double-publish? | Recovery revalidates the saved response before a missing commit, or redelivers the same final ID after a durable commit. No new inference or tool publication occurs. Crash-before, crash-after, uncertain-write and replay tests prove the boundaries. Repeated HTTP delivery can occur; exactly-once external display is not claimed. |
| Reviews still at most three? | Yes. `MAX_REVIEWS = 3`; exhaustion and continuation tests retain bounded failure. |
| Are provider retries still bounded? | Yes. Frozen legacy `jv-action-v1` retains the two-attempt replacement policy covered by the 91 replacement tests. Fresh JV-WIRE-V1 uses generation 1 plus wire-format corrections 2-5 only, with no generation 6. The policies are not stacked. |
| Active visuals still four? | Yes. Paired six/twenty/revisit flows and real engine six-image smoke verify the bound; inactive bytes remain references. |
| Engine exactly 0.149.1? | Yes. Offline real-engine/parity and temporary-install version verification require the pin; no npm source or engine edits. |
| Does provider integration preserve the client-execution boundary? | Yes. Production provider code received bounded Copy-capture, exact-button activation and cleanup compatibility changes, while shell, patch and image-view actions remain client-side only. Server-side JV-WIRE validation does not execute client tools. |
| Is simple conversation efficient? | Yes. Existing no-tool conversation bypasses agent review, and a second conversational turn after a committed task works. |

## Alternatives rejected

Ignoring open steps or inferring completion from files would fabricate model
attestation. Extra reminder text alone leaves v1's missing structural path.
Raising the review budget only prolongs that failure. A second update_plan call
adds avoidable failure and durability boundaries. Patching Codex, increasing image
or body limits, and changing providers do not address this client metadata issue.

## Reviewable runtime delta

For the completion-v2 delta audited here, `lib/jvcli/agent.py` owns the new
completion behavior. `update_plan` stays a stock client tool. The bridge records
derived provenance identities without modifying its tool call or result. The v2
completion records the plan before reconciliation, model reasons and the original
checkpoint. A persisted v1 task is rejected before any rewrite. Coordinated
Server/provider runtime changes are maintained separately; they validate and
capture structured transport without moving client tool execution to the Server.

Journal integrity detects corruption, not an attacker who controls the same OS
account and can recompute every checksum. Atomic rename/fsync assumes functioning
local filesystem durability. Upstream raw visual history remains bounded by the
unchanged 17 MiB ceiling; no unsafe epoch rollover is introduced.
