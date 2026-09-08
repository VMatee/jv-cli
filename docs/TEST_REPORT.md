# JV CLI test report

## Current Codex parity integration — 2026-09-08

Starting source: main at `d6b19df314cc2b6901059fe04ae1f8d3d361eecb`, VERSION 0.4.0.
The version and pinned engine 0.149.1 remain unchanged. The full compatibility
matrix, upstream source provenance, actual catalog, wire blockers and production
limitations are in [CODEX_PARITY.md](CODEX_PARITY.md). This section supersedes the
older subset descriptions below; their historical production evidence is not
new acceptance of this integration.

- Focused structured regressions: **38 passed**, no skips or failures.
- Full regression: **267 run, 266 passed, 1 skipped, 0 failed** on Python 3.10.12.
  The skip requires Python 3.11 `tomllib`.
- Existing real pinned-engine suite: **14/14 passed**, including legacy patch,
  resume, sandbox/write denial, network enabled/denied, and structured shell.
- New real pinned-engine parity suite: **8/8 passed** with existing Google Chrome.
  These cover local HTML/CSS/JS read/edit/build/test, update_plan and serial
  continuation, actual initial-image bytes, image-backed resume, exact view_image
  wire capture, and real browser screenshot/image-result capture.
- Both engine suites use scripted loopback responses: **zero live inference**.
  Image-result capture is not JV view_image transport acceptance or proof of
  provider visual reasoning.
- Manifest: **66 shipped source/documentation files**; ZIP: **67 entries** including
  the manifest. Two byte-identical builds, checksum, inventory exclusions, fresh
  extraction/verification, temporary-HOME installation, version and doctor checks
  passed. The temporary installation used the existing pinned engine explicitly;
  no runtime download or real user installation was changed.
- An initial full run had four expected stale-manifest integrity errors; after
  rebuilding the manifest the entire suite passed. No application regression
  failure remained.

Contract `52be8980e01828959df7712ddae17d077d69efcf` certifies image-bearing
function results and exact custom apply_patch. Live custom apply_patch plus shell
passed in three rounds with zero repairs and verified local output. Live initial
image returned `Structured attachments are unavailable for this provider
assignment`; view_image and the web screenshot loop were not submitted after that
deterministic account limitation. Production image acceptance remains P0 for this
account. Cross-user-turn JV conversation continuity and long-context/compaction
certification remain P1.
All source work is uncommitted/unpushed. No server/provider or installed-copy
changes were made. This tree is **not ready for release-candidate preparation**
because the required production image gates cannot run with this assignment.


## Earlier structured 0.4.0 candidate work — 2026-09-08

Baseline JV CLI commit: `278b0c86999f909cb39d8693d3c4b7b27eaa662c`; baseline source version was 0.3.3. After the structured implementation and controlled live acceptance passed, the release-candidate source was promoted to 0.4.0. The supplied local protocol-reference checkout was absent, so the public repository was read directly at immutable commit `73198196ef9f924cfcb08a93421f1fe6aa0aae7d`. The engine remains pinned to 0.149.1.

The automated suite ran 247 cases: 246 passed, one skipped because this Python 3.10 runtime lacks `tomllib`, and zero failed. New coverage exercises structured POST headers and mandatory fields, 202 creation, 200 replay, polling transitions, terminal/no-output invariants, malformed IDs/items/arguments, strict tool translation, exact continuation state, durable idempotency, ambiguous-POST reconciliation, same-key body binding, duplicate-publication prevention, unresolved restarts, replayed response/call IDs, persistence failure, opt-in configuration and unsupported inputs/tools. Existing `/v1/jobs`, job inspection/download, installation and session regressions remain passing.

Package verification covered 56 source/documentation files. Consecutive builds were byte-identical; checksum and archive inventory passed. An extracted archive passed verification, and a fresh temporary-HOME installation passed version and doctor checks using the repository's existing pinned engine through an explicit engine path. No engine download or update of the user's installed JV CLI was performed.

All 14 default real-engine checks passed with the real local `@openai/codex@0.149.1` binary. The new check captures the pinned engine's actual full-history requests and completes two scripted structured rounds through the authenticated loopback adapter: one validated `shell_command`, actual local fixture output, exact `call_id`, `previous_response_id`, resent instructions/tools, final message and zero client prompt repairs. This check uses scripted loopback model output and does not contact JV Server.

At that earlier checkpoint, structured mode remained opt-in through `JVCLI_AGENT_API=1`. The only certified remote-declared client tool is `shell_command` with its required string `command` argument; the engine remains the local executor and enforces its sandbox/network policy. Custom/freeform patch calls, hosted/MCP/web/image tools, non-text input, parallel calls, remote streaming, usage/reasoning exposure and full Responses compatibility remain unsupported. Legacy `/v1/jobs`, attachments, conversation IDs, generated-file downloads and text-agent correction behavior remain available and default.

The operator subsequently completed the controlled production client acceptance. The final audit below supersedes the earlier credential-blocked live status. The live run itself reported version 0.3.3; the source was promoted to 0.4.0 only after that evidence was audited, without repeating production inference.

### Final production structured acceptance — 2026-09-08

Result: PASS for the scoped two-round shell flow. The operator ran the repository source with `JVCLI_AGENT_API=1`, read-only mode and tool networking disabled against `https://ai.openjvspace.com`. Audit evidence consists of the existing private structured journal, session metadata, generated engine configuration, Codex execution history and the operator's terminal result. No additional production inference or server change was needed. No credentials, authentication headers, raw provider transcripts or hidden reasoning are included here.

Source HEAD was `278b0c86999f909cb39d8693d3c4b7b27eaa662c` with the uncommitted structured implementation described above; the implementation is not represented by that baseline commit alone. Protocol-reference revision: `73198196ef9f924cfcb08a93421f1fe6aa0aae7d`. JV CLI version: 0.3.3. The live Codex session metadata records engine version **0.149.1**, provider `jv`, originator `codex_exec`, and working directory `/tmp/tmp.w6gH0t7nMC`. Its generated configuration selects the authenticated loopback Responses provider, read-only sandbox, disabled tool networking and isolated session engine HOME.

| Evidence | Audited result |
| --- | --- |
| First response | `cj_75d768bfe05a45879e33d37e5ec083b1_20260908T075947360399Z` — completed; journal phase `continued` |
| Published call ID | `call_2d3a632aac602e262bedd435a9223c75` |
| Tool and arguments | `shell_command`, `{"command":"cat fixture.txt"}` |
| Local execution | One matching Codex function call and one function output; exit 0 |
| Harmless fixture stdout | `JV-STRUCTURED-LIVE-TEST-20260908` followed by a newline |
| Continuation | Exact first response ID in `previous_response_id`; exact published call ID in `function_call_output` |
| Second response | `cj_4d21572f585749dfad3abd685e2dfb38_20260908T080002919928Z` — completed; journal phase `final` |
| Final assistant text | Exactly `JV-STRUCTURED-LIVE-TEST-20260908`, present in both structured state and Codex task completion |
| JV CLI exit | 0, recorded in session metadata and confirmed by the operator |
| Model rounds / client prompt repairs | 2 / 0 |
| Unresolved published calls / nonterminal responses | 0 / 0 |

The entire Codex function output, including exit status, timing wrapper and fixture stdout, matches the continuation input byte for byte. Its canonical SHA-256 matches the digest saved on the first round. Both rounds have distinct, valid durable idempotency keys and normalized request bodies with `model=jv-ai`, `background=true`, `store=true`, `stream=false` and `parallel_tool_calls=false`. Instructions and the admitted shell schema were resent. There is no recorded uncertain-submission replay. Keys themselves are omitted from this report.

The selected processor submits to `/v1/responses` and polls `/v1/responses/{id}`; it never routes this flow through legacy `/v1/jobs`, `build_jv_prompt`, `parse_agent_output` or repair jobs. The journal records terminal completion for both rounds, and implementation validation/persistence precedes executable publication. Individual HTTP polling transitions are not retained by the journal, so this is implementation plus terminal-state evidence rather than a retained HTTP trace. No server-side audit log was needed or inspected.

The journal and Codex history contain exactly one executable call and one matching local result, with no evidence of duplicate publication or execution in this run. The fixture remains unchanged. This scoped proof does not claim exactly-once side effects across every crash boundary: an unresolved publication can require reconciliation, and a local timeout does not cancel remote work.

The audited code/tests match the manifest from the prior validation. The retained test log confirms **247 tests: 246 passed, one skipped, zero failed**; the retained real-engine report confirms **14/14 checks passed**. No implementation code changed during this audit, so no broad regression rerun or provider call was necessary. Legacy jobs, attachments, conversation support, inspection/downloads, authentication isolation, workspace protections and network policy remain covered by those regressions. Structured mode remains opt-in. The user's installed JV CLI and JV Server were not modified, and Codex was not upgraded.

Recommendation: ready for a subsequent explicit 0.4.0 release-candidate step with the current shell-only pilot scope and opt-in rollout. Additional tools, broader workloads, every crash boundary and full Responses compatibility are not certified by this acceptance.

## 0.3.3 validation — 2026-09-06

Automated suite: 228 cases, 227 passed, one skipped (Python 3.10 lacks tomllib), zero failed. Sixteen new regressions cover compact and verbose command display, visible failure output, unknown exit statuses, file-list layout, TTY prose wrapping, unchanged redirected text, preservation of code/URLs/tables, terminal-control sanitization, waiting-status deduplication, verbose flag placement, final-answer instructions and JSONL output with verbose enabled.

All thirteen default real-engine checks passed with engine 0.149.1. The real shell, patch, resume, response correction, network-enabled/disabled and workspace protection cases remain passing. This is a presentation change; command execution, API authentication and network policy are unchanged from 0.3.2. No live JV API jobs were submitted, so the model's adherence to the requested final-answer layout is not guaranteed.

## 0.3.2 validation — 2026-09-06

Automated suite: 212 cases, 211 passed, one skipped (Python 3.10 lacks tomllib), zero failed. The interactive pseudo-terminal test now checks default networking, explicit allow/deny flags and read-only behavior, including the generated engine configuration and no model jobs for local permission commands. Additional tests cover flag placement for exec/resume, conflicting flags and explicit network/read-only rejection before engine lookup or login.

All thirteen default real-engine checks passed with engine 0.149.1. New checks prove a network-enabled tool can reach a disposable loopback HTTP server while an outside-workspace write remains denied. Existing network-denied and read-only checks still pass. Scripted responses were used; no live JV API jobs, Rust installation, sudo configuration or sandbox bypass were involved.

## 0.3.1 validation — 2026-09-06

The automated suite completed 209 cases: 208 passed, one skipped (Python 3.10 lacks tomllib), zero failed. Seventeen new cases cover longer/mismatched JSON fences, preservation of nested code examples and patch contents, varied Rust-discovery probes, atomic batch and SSE rejection, per-turn reset, canonical repeated-action signatures, legitimate build/source-only outcomes, and both permission aliases under three policies in a pseudo-terminal.

All eleven default real-engine acceptance checks passed with the unchanged 0.149.1 engine. The two new checks decode a four-backtick final through the engine and simulate six missing-compiler probes, then verify that a seventh probe stops without executing any member of its batch. The existing shell, patch, resume, response-repair, outside-workspace write denial, read-only denial and tool-network denial cases remain passing.

This patch's tests used loopback scripted responses, not the live JV API. No Rust compiler was installed, no other project's toolchain was used, and the user's demo project was not modified. The discovery guard is a bounded heuristic, not a complete shell analyzer or a new filesystem sandbox. Prompt guidance cannot guarantee that every live model follows instructions; a missing compiler still prevents compilation.

The 0.3.1 source archive passed manifest and SHA-256 verification and was extracted into a fresh temporary directory. A default installation from that archive into a fresh temporary HOME installed engine 0.149.1 locally; the installed version command, all five doctor checks and installed manifest verification passed. The archive inventory contains public sources, tests, documentation and attribution, not runtime modules, local state, credentials or caches. Two final builds must remain byte-identical before publication.

## Historical 0.3.0 evidence

Date: 2026-09-05. Version remains 0.3.0. Status: **local validation passed; the client-context/protected-JSON candidate also completed a live Flask task**.

## Release preparation evidence

The suite contains **192 tests: 191 passed, one skipped, zero failed**, on Linux with Python 3.10.12. It retains all earlier 189 cases and adds three sandbox-aware web-verification and generic-error regressions. The skip intentionally requires Python 3.11's `tomllib`; generated configuration is also exercised through the real engine acceptance test. New fixtures are synthetic public examples, not captured private API responses.

A later user Flask run successfully edited the app and installed Flask but failed verification because a fixed /tmp log was read-only and a second compound command contained policy-rejected force deletion. The existing app passed a real-engine scripted read-only check using its own virtual environment and Flask test_client: HTTP 200, expected text and animation CSS. Its source hash was unchanged. The prompt now recommends this no-server verification path and explicitly respects deletion policy and supplied temporary-directory boundaries.

A separate authenticated live JV run with the updated guidance also verified that existing app in read-only mode: the model issued the local test_client command, all three assertions passed, and it reported the confirming result. No server, log, cleanup command or project edit was needed. This verifies the focused web-check path, not every possible task or model reply.

A separate delayed-response diagnostic against the real pinned engine confirmed that SSE comment heartbeats do not prevent its event-idle timeout: a one-second stream limit failed for a three-second fixture, while a six-second limit completed successfully. No live job was submitted by this diagnostic. The per-job polling default is now 300 seconds, configurable via JVCLI_WAIT_TIMEOUT, and the stream budget accommodates the initial job, two possible corrections and submission overhead. The whole-turn deadline remains independent. Longer local waiting does not resolve a server-side waiting_for_auth status.

Coverage includes:

- API authentication, jobs, polling, retry boundaries, attachments, downloads, and logout
- Responses adapter validation, SSE lifecycle, tool envelopes, limits, and malformed output
- bounded correction after confirmed completed jobs, atomic rejection of invalid batches, no resubmission after transport/submission failures, cancellation and request limits
- hidden password handling, credential/environment filtering, redaction, and private state
- engine subprocess behavior, resume flags, JSONL output, locks, and timeout/failure handling
- personal `~/.codex/config.toml` isolation while project-local agent configuration remains blocked
- normal temporary-HOME installation and launcher behavior
- portable isolation, PATH idempotence, guarded uninstall, and state-preserving upgrade
- deterministic archive naming, checksum creation, private/generated exclusions, canonical VERSION, and bootstrap checksum rejection

The real `@openai/codex@0.149.1` engine smoke test passed all nine default checks and the optional Flask check:

- `real_shell_execution_and_tool_result`
- `real_resume_and_custom_apply_patch`
- `labeled_json_patch_and_tool_result`
- `malformed_response_recovery_and_tool_result`
- `generic_provider_error_recovery`
- `repeated_invalid_response_fails_without_execution`
- `flask_app_creation_and_test_client_after_recovery` (optional)
- `outside_workspace_write_denied`
- `read_only_write_denied`
- `tool_network_denied`

The smoke test used scripted loopback responses and did not contact the live JV API. It actually ran the engine's shell/patch tools, resumed a thread, and verified tool output in the following model request. The Flask case created four files through the engine after an injected malformed patch response, then verified HTTP 200, “I love Thailand”, and animation CSS with Flask's test client. No server was left running.

The first optional Flask attempt could not import the user's personal Flask installation from the isolated tool HOME. A disposable /tmp virtual environment with Flask 3.1.3 fixed the test prerequisite; no system packages, personal Python packages, or sandbox flags were changed.

## Packaging and clean-install evidence

Two consecutive builds produced byte-identical ZIP files. The SHA-256 sidecar verified. The release was extracted to a fresh temporary directory and its `verify.sh` passed.

A default install from that extracted archive used a fresh temporary HOME. It downloaded and installed only the pinned engine inside `~/.local/share/jv-cli/runtime`, created `~/.local/bin/jvcli`, and passed:

- `jvcli --version`
- `jvcli doctor`
- engine version and initial/resume CLI contract checks

The archive inventory was inspected and contained no `.state/`, `.cache/`, `runtime/`, `.backups/`, `dist/`, local environment files, bytecode, credentials, or session data.

## Live-service diagnosis and acceptance

With user-authorized authentication, live diagnostics reproduced the old behavior: the model claimed a client workspace was absent without a supporting local tool result. Explicitly distinguishing the external client from the API server allowed a real local marker read. The old client still rejected all three file-writing replies in a Flask attempt.

Completed-job inspection and a controlled round-trip probe found Markdown-like damage to unfenced JSON: escaped array brackets/patch markers, double-underscore Python names converted to bold markers, and lost quote escaping. A requested code block preserved the JSON and code exactly but arrived with a standalone JSON language badge before the fence. The candidate accepted only that narrow wrapper; no damaged code was guessed or rewritten. The internal server component responsible for the presentation conversion was not inspected.

The same prompt/parser behavior now applied to the project was first tested in a temporary candidate using the live JV API and real pinned engine. An ordinary Flask task completed with **seven model jobs, zero response corrections, exit code 0**:

- local tools created app.py, templates/index.html, static/style.css and requirements.txt;
- Flask 3.1.3 was installed into the disposable project's .venv, not globally;
- all six agent test_client checks passed: page status, expected text, CSS link, CSS status, animation and reduced-motion support;
- an independent real HTTP test on a temporary 127.0.0.1 port confirmed the page and CSS responses, and shut down the server;
- a preexisting marker file was unchanged, and the user's original project was not edited.

Credentials were entered through hidden prompts, not included in source, command arguments, public fixtures or reports. The diagnostic sequence used 16 model jobs across the baseline, comparison probes and successful candidate; packaging/regression checks used no additional live jobs. Session/job identifiers and private responses are excluded from this public report.

This is evidence for one successful live task, not certification of every server-assigned model, every task, or all future replies. A valid final explanation and exit code 0 can still misdescribe a task; actual tool results and deliverable tests remain important. Start a fresh session after updating rather than continuing a history with mistaken environment claims.

The workflow targets Python 3.10 through 3.13. Hosted CI results are separate post-push evidence, not part of these local results.

## Limitations

Tests do not prove freedom from all defects or certify every Linux kernel. Coding mode replays bounded history into independent JV jobs rather than reusing server conversation IDs. True model token streaming, hosted tools, audio input, server-job cancellation, ARM64, Windows/macOS, and automatic release-based `jvcli update` are not implemented. Initial structured images are now supported as described in the latest parity audit.

Checksums detect corruption but are not signatures. npm, GitHub release publishing, the configured JV API, and the user's selected projects remain trust boundaries.
