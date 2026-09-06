# JV CLI contributor and agent guide

This guide applies to contributors working on this repository. It is not the runtime model prompt and does not grant extra permissions to JV CLI. The singular `agent.md` file points here; maintain substantive guidance in this file.

## Current baseline

- Product: JV CLI. User command: `jvcli`.
- Read `VERSION` for the current source version; the documented baseline is 0.3.3.
- Keep the known-good engine pinned to `@openai/codex@0.149.1`. Do not upgrade it as part of unrelated work.
- Plain `jvcli`, `exec` and `resume` use workspace-write mode with tool networking enabled.
- `--no-network` disables tool networking. `--read-only` denies writes and tool networking. Explicit `--read-only --allow-network` is rejected.
- `/permissions` and `/permission` report policy locally; they do not submit a model job or change policy.
- There is no YOLO flag, automatic privilege elevation or passwordless-sudo setup. Do not change sudoers, global services or another application's configuration as a routine implementation step.
- `--verbose` exposes detailed commands and bounded output. `exec --json` remains JSONL on stdout with diagnostics on stderr.
- A source version on `main` does not mean a tagged GitHub Release exists. Do not create a tag or Release without an explicit request.

## Inspect before changing

Read the relevant source and tests, `README.md`, and the focused documents under `docs/`. Check `git status`, the current branch and remotes first. Preserve unrelated working-tree changes. Use small, reviewable patches; do not remove working functionality merely to simplify the code.

Do not alter user demo workspaces, install compilers, borrow private toolchains from other projects, reinstall the user's application, or contact the live JV API unless that action is in the current task's scope. Temporary test installations are separate from the user's real installation.

## Architecture and important files

- `lib/jvcli/cli.py`: command parsing, authentication flow, session locks, isolated engine configuration/environment, terminal display and subprocess lifecycle.
- `lib/jvcli/protocol.py`: strict text-agent envelopes, tool catalog/schema validation, bounded history, formatting recovery and runtime model instructions.
- `lib/jvcli/adapter.py`: authenticated loopback Responses bridge, JV job orchestration, correction budgets and repeated-action/discovery limits.
- `lib/jvcli/transport.py`: JV API authentication, HTTPS, jobs, polling, uploads/downloads and transport failures.
- `lib/jvcli/safety.py`: private paths/state, safe serialization, redaction and terminal sanitization.
- `scripts/manage.py`: user/portable installation, guarded uninstall, idle checks, source backups/upgrades and package manifests.
- `scripts/build_release.py` and `scripts/build-release.sh`: deterministic source ZIP and SHA-256 sidecar, using `VERSION`.
- `scripts/engine_smoke.py`: real pinned-engine acceptance with scripted loopback responses.
- `tests/`: automated mock, protocol, transport, CLI, terminal and installation/release regressions.
- `.github/workflows/`: test and explicitly tag-triggered release automation.

The API/model environment is separate from the user's computer. Only delegated client tool results prove that a local command ran or a file changed. Do not redesign the JV server protocol or make the model use server-native tools to reach client workspaces.

## Preserve security and isolation

Default installation owns `$HOME/.local/share/jv-cli/` and `$HOME/.local/bin/jvcli`. Source, runtime, state, caches and backups stay under the application root. Portable mode keeps those files inside its extracted folder and creates no normal user launcher or installation. Do not silently edit shell startup files; `--add-path` is explicit and idempotent.

Keep `CODEX_HOME`, tool HOME and temporary paths isolated within JV CLI state. Do not read, replace or rely on the user's personal Codex configuration. Preserve selected-workspace protections, read-only enforcement and explicit network denial. Enabled networking is not permission for system-wide writes, root access or installation of system toolchains. Installation isolation is not a VM, and arbitrary reads outside the workspace are not guaranteed blocked.

Preserve hidden password input, no `--password` argument, memory-only bearer tokens and exclusion of JV credentials from child engine processes. Never print or commit real passwords, tokens, private keys, private API replies or local sessions. Treat source-code field names and synthetic test credentials differently from real secrets. Never use a production credential as a regression fixture.

Keep `.state/`, `.cache/`, `runtime/`, `.backups/`, `dist/`, environment files, local configurations, sessions, npm modules and Python bytecode out of Git and source archives. Inspect intended public files before regenerating the manifest: the builder discovers non-excluded source files, including untracked ones.

Do not weaken sandboxing or enable root execution to make a test pass. Do not kill an unrelated process to free a port. Prefer bounded localhost tests on an ephemeral port with guaranteed shutdown; for Flask, prefer `test_client`. Respect tool-policy refusals rather than evading them with another interpreter.

## Protocol and output invariants

- Accept only validated whole response envelopes, including matching JSON fences and the supported standalone JSON badge. Preserve code and patch contents; do not guess truncated commands.
- Validate an entire tool batch before emitting any tool from it. Unknown tools and invalid arguments must fail closed.
- Retry only confirmed completed jobs with rejected model output, within the existing two-correction budget. Do not blindly resubmit uncertain network submissions.
- Preserve per-job and whole-turn deadlines, cancellation behavior, request limits, repeated-action limits and the bounded Rust-discovery heuristic. A timeout does not cancel or authenticate a remote job.
- Never present a failed or unknown command exit as success. Keep error details available and redact known secrets before display.
- Human-readable rendering must not rewrite tool execution or corrupt JSONL output, copied code or redirected final text. Prompt formatting guidance is not a guarantee about model behavior.

## Validation workflow

Keep existing tests and add targeted regressions for behavior changes. Automated installation/authentication tests must use temporary HOME/state/workspace directories and synthetic credentials; never modify the real developer HOME. Real-engine acceptance uses dedicated disposable fixtures under JV CLI state, not user projects.

After reviewing intended public files, refresh and verify the manifest through the package builder:

```bash
./scripts/build-release.sh
./test.sh
./verify.sh
python3 -B scripts/engine_smoke.py
```

The 0.3.3 baseline is 228 automated cases (227 passed and one skip on Python 3.10 because `tomllib` needs Python 3.11) and 13 real-engine checks. Report the actual new totals, skips and failures instead of copying these numbers. Scripted engine checks are not live-model acceptance.

For release/install changes, also verify the ZIP checksum, inspect the inventory, extract into a fresh temporary directory, run the extracted `verify.sh`, and test installation/version/doctor with a fresh temporary HOME. Build twice when checking reproducibility. Runtime modules, credentials and sessions must not be packaged.

Do not ask for a production password for documentation, builds or publication. Live API tests require explicit scope and must be reported separately from mock/loopback tests.

## Documentation and publication

Keep README behavior, command help, `docs/CONFIGURATION.md`, security notes, the changelog and test reports consistent with the code. `VERSION` is canonical; documentation-only updates do not require a version bump. `MANIFEST.sha256` must match all shipped files after documentation edits.

Retain `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `third_party/openai-codex/LICENSE` and `third_party/openai-codex/NOTICE`. Product branding does not replace upstream attribution.

Commit or push only when requested. Before publication, inspect the complete staged file list/diff and scan for private state and secrets. Preserve the repository-specific `core.sshCommand` and use only the deploy identity authorized for this repository; never read or publish its private key. Check remote `main` against local history and stop on unexpected changes. Push normally, never force-push. Do not create release tags or GitHub Releases unless separately requested.

Report what changed, validation results, any untested live behavior, commit/push status and remaining limitations. Do not claim an installed copy was updated when only repository documentation changed.
