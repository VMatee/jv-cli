# JV CLI 0.3.0 test report

Date: 2026-09-05. Version remains 0.3.0. Status: **local adapter/tool checks passed; live JV coding retry still required**.

## Release preparation evidence

The suite contains **172 tests: 171 passed, one skipped, zero failed**, on Linux with Python 3.10.12. It retains the earlier 147 cases and adds 23 response-format/recovery cases plus two end-to-end recovery/logout/session-metadata cases. The skip intentionally requires Python 3.11's `tomllib`; generated configuration is also exercised through the real engine acceptance test.

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

The real `@openai/codex@0.149.1` engine smoke test passed all eight default checks and the optional Flask check:

- `real_shell_execution_and_tool_result`
- `real_resume_and_custom_apply_patch`
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

## Live-service limitation

The user's supplied live transcript demonstrated successful authentication, a successful direct `ask`, and a real shell command, followed by a malformed model tool response. A job can report `succeeded` while its answer is unusable for coding. The exact rejected raw answer was not available locally, so regressions cover representative malformed replies and the exact two reported generic error messages, not a claimed replay of that raw payload.

No live JV job was submitted during this fix. Authentication requires the user's private password and live jobs can consume quota. Offline success proves the recovery/tool path with controlled replies, not that the server-assigned model will now reliably complete the user's Flask task. A fresh live coding session remains required.

The workflow targets Python 3.10 through 3.13. Hosted CI results are separate post-push evidence, not part of these local results.

## Limitations

Tests do not prove freedom from all defects or certify every Linux kernel. Coding mode replays bounded history into independent JV jobs rather than reusing server conversation IDs. True model token streaming, hosted tools, image/audio input, server-job cancellation, ARM64, Windows/macOS, and automatic release-based `jvcli update` are not implemented.

Checksums detect corruption but are not signatures. npm, GitHub release publishing, the configured JV API, and the user's selected projects remain trust boundaries.
