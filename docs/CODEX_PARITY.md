# 0.4.3 completion-liveness and visual-context verification

Current verification retains the scripted stock-engine, parity, committed-turn and
six-image completion checks with unmodified Codex 0.149.1. The coordinated
production stack additionally passed Scenario 01 live acceptance on 2026-09-12.
See [TEST_REPORT.md](TEST_REPORT.md). Historical sections below retain their
original scope and deployment statements; they are not rewritten as if they had
been live-accepted at the time.

# Offline bounded visual context candidate — 2026-09-09

## 0.4.2 candidate scope

The new [agent completion architecture](AGENT_COMPLETION.md) adds a local metadata tool and bounded completion review without modifying stock Codex 0.149.1. `scripts/agent_smoke.py` exercises actual view_image, no-network shell execution, evidence, withheld final, completion and thread resume against scripted inference. Historical sections below describe earlier contract snapshots; the overnight audit is authoritative for this candidate.


JVCLI 0.4.1 separates historical replay validation from active visual context.
The coordinated Server WIP retains four recent distinct images for inference and
compiles older observations as factual references. Neither production Server nor
the installed JVCLI has been updated. Public contract revision `52be898` remains
unchanged; this new extension requires independent audit and explicit deployment.
See [the architecture note](VISUAL_CONTEXT.md) for budgets, reinspection and limits.
The historical certification below does not certify live grading or this new
working-set behavior. No Scenario 01 retry has been run for this work.

# Current Codex core integration — contract 52be898

The accepted public contract is now [52be8980e01828959df7712ddae17d077d69efcf](https://github.com/VMatee/jv-llm-api-example/blob/52be8980e01828959df7712ddae17d077d69efcf/docs/responses-api.md).
Both earlier server-contract blockers are removed. The client now forwards the
exact pinned custom apply_patch declaration and freeform input, string custom
results, and image-only function result arrays. All tools still execute locally.
Production custom-tool acceptance passed. Production image acceptance is blocked
by the tested account's server-side provider assignment; see TEST_REPORT.md.

The resumed starting state was main at d6b19df314cc2b6901059fe04ae1f8d3d361eecb,
VERSION 0.4.0, with 16 modified tracked files and four untracked additions from
the previous work. Those changes were retained. Codex remains 0.149.1, tag
rust-v0.149.1, upstream ff29a44391deccde0aba0f8390337d7f3c319ea4.

## Current supported wire forms

- shell_command and update_plan retain their existing JSON function form.
- view_image is the exact pinned function with a required path. Codex performs
  its sandboxed local read; JV receives the resulting image bytes, never the path.
- function_call_output accepts a string, or 1–4 input_image items only. Mixed text,
  file, audio or encrypted arrays fail closed. PNG/JPEG/WebP and auto/high detail
  are supported. Canonical base64, MIME signature, byte/count and metadata bounds
  are checked locally; complete decode and attachment lifecycle remain server-owned.
- apply_patch is a custom grammar/lark tool. Its exact grammar SHA-256 is
  d6367f4826ed608c424b0a308f3d6163527df63c22513d089b91863552f8bfeb.
  The shipped lib/jvcli/apply_patch.lark matches both the accepted public fixture
  and pinned upstream source. Changed grammar or unsupported custom fields fail.
- custom_tool_call carries freeform input unchanged (nonempty, at most 32 KiB).
  Codex validates and executes it. custom_tool_call_output is a string of at most
  32 KiB, retained byte-for-byte including whitespace. An array is rejected.
- Both call classes share durable publication protection and exact call/result
  class, ID, predecessor and per-round key correlation. Tool output arrays are
  neither flattened nor moved into user messages. Ordinary continuations send
  only the new result, without replaying original attachments from the client.
- Normalized structured metadata is limited to 64 KiB; image-bearing requests to
  17 MiB. The private journal remains bounded to 64 MiB. Context attachment limits
  remain server-enforced across replayed rounds.

There is no structured prompt repair or fallback to legacy jobs. New user turns
still use the existing engine-history replay behavior; long-context compaction
and full server conversation mapping remain uncertified P1 differences. Plan-only
request_user_input remains unreachable in JV's default exec/line UI. Goal tools,
multi-agent tools, audio, mentions, full skill UI, MCP, hosted tools and parallel
calls remain optional P2; generic staged-file CLI UX remains P3.

## Reproducible validation

Run ./scripts/build-release.sh, ./test.sh, ./verify.sh,
python3 -B scripts/engine_smoke.py and
python3 -B scripts/parity_smoke.py --browser /usr/bin/google-chrome.
The parity suite now uses the real structured processor for image results and
patches, including local custom execution, multi-round continuation, resume and
browser screenshot → view_image → CSS patch → build/browser geometry and click test.
Scripted loopback results alone do not certify production visual reasoning.

After offline checks pass, scripts/core_live_smoke.py runs four bounded production
scenarios with a hidden terminal password prompt and disposable state. It checks
unprompted image color facts, exact view_image bytes, local patch execution, and a
web screenshot/correction loop. Its test measures rendered element geometry and
button interaction using Chrome; source files are never attachment uploads.
No password/bearer token is saved, and the report includes safe metadata only.

## Production result

The first production attempt exposed and then verified a client schema fix. JV
returned `JV-INPUT-001: Strict object schemas must require every declared property`.
The bridge now forwards only required strict subsets: `shell_command.command` and
`update_plan.plan`; Codex retains its full local tool behavior. Focused and real
engine regressions pass after this correction.

The next initial-image request returned the contract's account-routing limitation:
`JV-INPUT-001: Structured attachments are unavailable for this provider
assignment`. No image inference completed. This agrees with the public contract,
which currently certifies attachments only for a ChatGPT-capable assignment. JV
CLI cannot change account routing and no server/provider source was modified.
Initial-image, view_image and web screenshot production scenarios therefore remain
unaccepted for the supplied account.

The independent custom-tool scenario passed in production in three rounds:
provider custom apply_patch call, exact local custom result, local shell read and
final response. The disposable file matched the hidden marker, exact predecessor
and call/result classes were journaled, and prompt repairs remained zero. This
also provides live text plus shell continuation evidence. The token was revoked
after the run and no credentials were saved.

Current decision: the client has no known P0 code gap, but the required production
image gates remain a P0 acceptance blocker for this provider assignment. Source is
not declared release-candidate ready without a small run using an account whose
assignment supports structured attachments.

JV Server source changed: NO. ChatGPT provider changed: NO.
Gemini provider changed: NO. Installed JV CLI changed: NO.
VERSION unchanged; no commit, push, tag or release. Release-candidate ready: NO.

---

# Historical audit before contract 52be898

The following records the previous checkpoint; its contract-blocker and test-total
statements are historical and superseded by the current integration above.

# Codex structured integration audit — 2026-09-08

**Not ready for release-candidate preparation.** Initial images and serial local
coding work in offline bridge and real-engine checks. The published JV contract
does not specify the array-valued image tool results required by `view_image`, or
the custom/freeform tools required by `apply_patch`. These P0 paths remain blocked.
No production acceptance is claimed.

## Provenance and scope

Starting branch: `main`. Starting HEAD:
`d6b19df314cc2b6901059fe04ae1f8d3d361eecb`. Starting and final VERSION: `0.4.0`.
Remote: `git@github.com:VMatee/jv-cli.git`. Existing uncommitted edits to
`AGENTS.md`, `README.md`, and `MANIFEST.sha256` were preserved; the initial patch
was saved in ignored `.cache/parity-audit/starting.patch` before implementation.
No commit, push, tag, release, installed-copy update, or provider change was made.

The installed repository-local engine reports `0.149.1`. Its exact source is
[OpenAI Codex rust-v0.149.1](https://github.com/openai/codex/tree/rust-v0.149.1),
commit `ff29a44391deccde0aba0f8390337d7f3c319ea4`. No current Codex main behavior
was substituted for this tag.

The fetched [JV reference main](https://github.com/VMatee/jv-llm-api-example)
was exactly `19a16655a1fd11d83cac94672733ab587058eb4a`. The authoritative
[Responses guide at that commit](https://github.com/VMatee/jv-llm-api-example/blob/19a16655a1fd11d83cac94672733ab587058eb4a/docs/responses-api.md)
defines user-message images and staged files. Its README still calls the pilot
text-only, so that README statement is stale. The guide explicitly limits
structured attachments to a ChatGPT-capable account assignment and says Gemini
attachments fail closed. This client does not override server routing.

## UserInput audit

The exact enum in `codex-rs/protocol/src/user_input.rs` contains seven variants:
`Text`, `Image`, `LocalImage`, `Audio`, `LocalAudio`, `Skill`, `Mention`.
`protocol/src/models.rs::ResponseInputItem::from_user_input` defines their
provider serialization. There is no native generic file variant here.

| Variant | JV CLI surface | Pinned provider representation | Client decision / server support |
| --- | --- | --- | --- |
| Text | Interactive, exec, resume | Text content | Supported |
| Image | No direct data-URL CLI option; bridge accepts engine form | `input_image` data URL | Supported PNG/JPEG/WebP user content |
| LocalImage | `exec/resume --image PATH` | Local read/preparation becomes labelled text plus `input_image` | Workspace-only private snapshot; same image transport |
| Audio | No native launcher option | `input_audio` | Reject; public contract excludes audio |
| LocalAudio | No native launcher option | Local conversion to audio content | Unsupported, optional coding parity |
| Skill | No structured picker in JV's line-oriented UI | Locally selected skill instructions, not a server Skill item | Preserve engine-local resolution and isolated homes |
| Mention | No structured picker/connectors in JV UI | Local selection metadata; no standalone provider Mention item | No invented connector or provider semantics |

`Skill` and `Mention` are omitted by the generic provider-item conversion;
core/extensions resolve their contextual effects. The skills selection sources
are `codex-rs/skills/src/selection.rs` and `codex-rs/ext/skills/src/selection.rs`;
plugin mentions are handled under `core/src/plugins/mentions.rs`. Local textual
skill context is ordinary text to the bridge. Personal Codex configuration is
not loaded. Interactive skill selection and connector behavior are not certified.

## Actual tool catalog

Captured from the unmodified engine under `_write_engine_config(...,
structured=True)`, not inferred from upstream defaults:

| Tool | Wire kind | Classification | Reason |
| --- | --- | --- | --- |
| shell_command | function | PASS | Local execution and string result; command, workdir, login, timeout_ms; no escalation fields |
| update_plan | function | PASS | Exact plan JSON schema and local result continuation |
| request_user_input | function | NOT RELEVANT in current mode | Engine declares it Plan-only; JV launcher has no Plan-mode UI |
| apply_patch | custom, grammar/lark | MISSING, P0 | No published JV custom-tool contract |
| view_image | function | MISSING, P0 | Successful result is an image content array, not a string |
| multi_agent_v1 | namespace | MISSING, P2 | close_agent, resume_agent, send_input, spawn_agent, wait_agent; not forwarded |
| get_goal / create_goal / update_goal | function | MISSING, P2 | Declared upstream, not certified/forwarded |

Only shell_command and update_plan are forwarded. Unknown response tools fail
before publication. JV does not execute any of these tools remotely.

## Exact P0 wire gaps and local reproductions

Pinned `core/src/tools/handlers/view_image.rs` reads through the configured
filesystem sandbox, validates the local image and emits a content-array tool
result. The captured provider-facing shape is:

```json
{
  "type": "function_call_output",
  "call_id": "call_capture",
  "output": [{
    "type": "input_image",
    "image_url": "data:image/png;base64,<actual bytes omitted>",
    "detail": "high"
  }]
}
```

The public guide only defines `output` as text and defines attachments in **user
content**. Moving a tool image into a user message would invent role, attachment
lifecycle and continuation semantics. This implementation does not do that.
The exact local rejection is:

```text
Structured function output must be bounded text; the public JV contract does not define content-array tool results (view_image)
```

Required additive contract: array-valued `function_call_output.output`, allowed
content types/roles, size and detail limits, attachment lifecycle and replay
semantics on tool continuation. A string containing JSON is not equivalent.

Pinned `core/src/tools/handlers/apply_patch_spec.rs` declares:

```json
{"type":"custom","name":"apply_patch","format":{"type":"grammar","syntax":"lark","definition":"<pinned apply_patch.lark>"}}
```

The required response and continuation shapes are:

```json
{"type":"custom_tool_call","id":"ctc_example","call_id":"call_example","name":"apply_patch","input":"*** Begin Patch\n*** Add File: example.txt\n+example\n*** End Patch"}
```

```json
{"type":"custom_tool_call_output","call_id":"call_example","output":"Success. Updated the following files:\nA example.txt"}
```

Required additive contract: custom tool declarations, freeform `input` retained
byte-for-byte, custom output continuation, validation and durable call identity.
The minimal localhost request offering only the custom tool with
`tool_choice:"required"` receives HTTP **400** from JV CLI:

```text
A tool is required but no certified structured tool was offered
```

`tests/test_structured_images.py` exercises that HTTP rejection with zero JV
submissions and zero prompt repairs. Custom calls are never disguised as JSON
function calls. Existing legacy custom patch execution still passes the real
engine suite.

These are proven **client rejections and public-contract omissions**, not a
claim that a production server returned a particular error. No live custom/image
result probe was submitted. An undocumented capability cannot be certified from
this reference; obtain an explicit public contract before enabling either path.
JV Server and provider sources remain frozen.

## Initial-image implementation and privacy

```bash
JVCLI_AGENT_API=1 ./jvcli exec --image screenshot.png "Explain this screenshot"
```

Repeat `--image` up to four times. `resume` accepts the same option for a new turn.
Relative paths are workspace-relative; absolute paths must lie beneath that
workspace. Parent traversal, symlinks at every component, nonregular files, and
oversized files are rejected. Directory-FD reads and private exclusive snapshot
files prevent a swapped original path from redirecting Codex's subsequent read.
The bridge never opens a path found in provider-facing image content.

PNG/JPEG/WebP data URLs retain their actual bytes and ordered text/image parts.
The client checks MIME signatures, base64, detail (`auto`/`high`), four images,
5 MiB each, 12 MiB total decoded, 17 MiB request size and separately bounded
100 KiB metadata. Signature preflight is not full image certification: Codex and
JV perform decoding. Unsupported content is rejected, not OCRed or flattened.
Original image data is not resent for an ordinary tool continuation. A new user
turn currently replays engine history into a new JV conversation, including any
initial images still in that history; this is a known conversation difference.

Private durable journals retain exact request bodies/keys for uncertain replay;
the structured journal now has a 64 MiB bound. Other private JSON files keep the
existing 1 MiB bound. Saved images/history are private session data, not diagnostic
logs. Base64 data URLs are removed from diagnostic rendering. Credentials remain
memory-only where previously designed, excluded from child environments, with
hidden password input and isolated CODEX_HOME/tool HOME.

## Compatibility matrix

PASS below means scoped offline/real-engine acceptance, **not production acceptance**.
P0 blocks a requested core path; P1 is an important behavioral difference; P2 is
optional Codex parity; P3 is a JV extension.

| Area | Status | Gap / evidence |
| --- | --- | --- |
| TEXT | PASS | Async create/poll and strict native output; prompt repairs = 0 |
| INITIAL IMAGE | PARTIAL | Bridge HTTP and actual bytes pass; live visual answer untested, P1 |
| LOCAL IMAGE | PARTIAL | Real engine --image, private snapshots, unsafe-path tests pass; live untested, P1 |
| VIEW_IMAGE | MISSING | Local capture works; JV image-result contract absent, P0 |
| SHELL_COMMAND | PASS | Real local reads/edits/build/tests and exact string continuation |
| APPLY_PATCH | MISSING | Structured custom contract absent, P0; legacy patch still works |
| OTHER ACTUAL CODEX TOOLS | PARTIAL | update_plan passes; goal/multi-agent tools omitted, P2 |
| STRUCTURED TOOL OUTPUT | PARTIAL | String supported; arrays/custom outputs rejected, P0 for visual path |
| SKILL | PARTIAL | Engine-local context preserved; no structured picker/certification, P2 |
| MENTION | NOT USED | No connector UI/provider semantics, P2 |
| AUDIO | NOT USED | Unsupported public modality; not needed for coding, P2 |
| CONVERSATION | PARTIAL | Serial tool chain passes; new user turns start fresh JV history replay, P1 |
| RESUME | PASS | Real structured image-backed resume plus existing legacy tests |
| COMPACTION | PARTIAL | No compact endpoint; long-context compaction not certified, P1 |
| PARALLEL TOOLS | PARTIAL | Forced false; serial coding passes, performance limitation, P2 |
| WORKSPACE FILES | PASS | HTML/CSS/JS/package.json read/edit/build locally; no uploads |
| GENERIC JV FILE EXTENSION | JV EXTENSION | Public staged files exist; no new CLI option implemented, P3 |
| SANDBOX | PASS | Existing real-engine write/read-only checks and safe image ingress |
| NETWORK | PASS | Existing explicit enabled/denied checks; defaults unchanged |
| AUTH | PASS | Synthetic isolation regressions; production authentication untested |
| LEGACY JOBS | PASS | Existing mock and real-engine regressions preserved |

The pinned engine has `FunctionCallOutputBody::Text` and `ContentItems`, including
image, text, audio and encrypted-content items. Custom outputs share that payload
type. Unsupported arrays are rejected even when they contain only text; no silent
flattening is used. Shell exit status and call IDs remain intact inside actual
Codex output strings.

Compaction is not purely local summarization: the engine can request a model
summary through its ordinary stream path when remote compaction is unavailable,
then replace local history. `core/src/session/turn.rs::run_auto_compact` selects
using provider capabilities; `core/src/compact.rs` performs local-history
replacement. JV's adapter has no `/responses/compact` endpoint or usage accounting.
Current 16-message/100 KiB metadata bounds can stop long sessions; those remain a
P1 limitation rather than an invented server summary implementation.

## Acceptance record

Run the reproducible checks:

```bash
./scripts/build-release.sh
./test.sh
./verify.sh
python3 -B scripts/engine_smoke.py
python3 -B scripts/parity_smoke.py --browser /usr/bin/google-chrome
```

`parity_smoke.py` uses an existing Chrome installation only when explicitly
selected. It uses no browser sandbox bypass and no package installation. Its
browser fixture uses short private state paths because Chrome's Unix socket
paths have an OS length limit. Chrome screenshot capture requires the normal
network-enabled tool policy here; a network-denied exploratory run failed with
`setsockopt: Operation not permitted`. The policy was not bypassed.

The web fixture contains index.html, style.css, app.js and package.json. Actual
Codex tools read the files, edit CSS, run `npm run build` and `npm test`, and return
`WEB_TEST_OK`. A separate browser fixture has an invisible white-on-white heading;
Chrome renders it and real view_image returns its PNG bytes to a local capture
processor. The local capture deliberately does not claim a JV submission or a
model's visual diagnosis/correction. The complete live screenshot reasoning loop
remains blocked by the P0 result contract.

Production text+shell, initial image, view_image, web/UI correction, and custom
apply_patch acceptance are **NOT RUN**. No password was requested through chat,
no production credentials were read, and no live inference was consumed. These
must be performed with a user-controlled hidden terminal prompt after the
relevant contract and offline gates pass. The stock-engine checks use scripted
responses and cannot prove provider perception, routing, readiness, billing or
production recovery behavior.

Validation totals and final package checks are recorded in TEST_REPORT.md.

JV Server source changed: **NO**. ChatGPT provider source changed: **NO**.
Gemini provider source changed: **NO**. User's installed JV CLI changed: **NO**.
VERSION bump: **NO**. Release-candidate ready: **NO**.
