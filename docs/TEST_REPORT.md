# JV CLI 0.3.0 test report

Date: 2026-09-05. Version remains 0.3.0. Status: **local validation passed; the client-context/protected-JSON candidate also completed a live Flask task**.

## Release preparation evidence

The suite contains **186 tests: 185 passed, one skipped, zero failed**, on Linux with Python 3.10.12. It retains all earlier 172 cases and adds 14 protected-JSON/language-badge, value-preservation, rejection, prompt and SSE regressions. The skip intentionally requires Python 3.11's `tomllib`; generated configuration is also exercised through the real engine acceptance test. New fixtures are synthetic public examples, not captured private API responses.

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

Tests do not prove freedom from all defects or certify every Linux kernel. Coding mode replays bounded history into independent JV jobs rather than reusing server conversation IDs. True model token streaming, hosted tools, image/audio input, server-job cancellation, ARM64, Windows/macOS, and automatic release-based `jvcli update` are not implemented.

Checksums detect corruption but are not signatures. npm, GitHub release publishing, the configured JV API, and the user's selected projects remain trust boundaries.
