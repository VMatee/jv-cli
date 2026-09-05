# JV CLI 0.3.0 test report

Date: 2026-09-05. Status: **stable release candidate passed local publication gates**.

## Release preparation evidence

The final suite contains **147 tests** covering the original 132 cases, 12 public-install/release cases, and three personal-Codex-isolation regressions. It passed on Linux with Python 3.10.12. One test that intentionally requires Python 3.11's `tomllib` was skipped; the generated configuration is exercised through the real engine acceptance test.

Coverage includes:

- API authentication, jobs, polling, retry boundaries, attachments, downloads, and logout
- Responses adapter validation, SSE lifecycle, tool envelopes, limits, and malformed output
- hidden password handling, credential/environment filtering, redaction, and private state
- engine subprocess behavior, resume flags, JSONL output, locks, and timeout/failure handling
- personal `~/.codex/config.toml` isolation while project-local agent configuration remains blocked
- normal temporary-HOME installation and launcher behavior
- portable isolation, PATH idempotence, guarded uninstall, and state-preserving upgrade
- deterministic archive naming, checksum creation, private/generated exclusions, canonical VERSION, and bootstrap checksum rejection

The real `@openai/codex@0.149.1` engine smoke test passed all five checks:

- `real_shell_execution_and_tool_result`
- `real_resume_and_custom_apply_patch`
- `outside_workspace_write_denied`
- `read_only_write_denied`
- `tool_network_denied`

The smoke test used a scripted loopback model and did not contact the live JV API.

## Packaging and clean-install evidence

Two consecutive builds produced byte-identical ZIP files. The SHA-256 sidecar verified. The release was extracted to a fresh temporary directory and its `verify.sh` passed.

A default install from that extracted archive used a fresh temporary HOME. It downloaded and installed only the pinned engine inside `~/.local/share/jv-cli/runtime`, created `~/.local/bin/jvcli`, and passed:

- `jvcli --version`
- `jvcli doctor`
- engine version and initial/resume CLI contract checks

The archive inventory was inspected and contained no `.state/`, `.cache/`, `runtime/`, `.backups/`, `dist/`, local environment files, bytecode, credentials, or session data.

## Not re-run

The live JV API smoke test was not repeated during publication because it was not necessary for packaging and would require an interactive password and consume service quota. Username/password authentication, direct job behavior, tool execution, and multi-turn behavior were already represented by the supplied working baseline and automated/mock coverage.

GitHub Actions has not run until the repository is pushed. The workflow targets Python 3.10 through 3.13; those hosted runs remain post-push evidence.

## Limitations

Tests do not prove freedom from all defects or certify every Linux kernel. Coding mode replays bounded history into independent JV jobs rather than reusing server conversation IDs. True model token streaming, hosted tools, image/audio input, server-job cancellation, ARM64, Windows/macOS, and automatic release-based `jvcli update` are not implemented.

Checksums detect corruption but are not signatures. npm, GitHub release publishing, the configured JV API, and the user's selected projects remain trust boundaries.
