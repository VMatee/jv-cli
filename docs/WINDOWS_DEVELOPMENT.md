# Native Windows / PowerShell development plan

## Status and purpose

Preparation steps 1 and 2 are complete. Phase 3 has a static inventory and an
offline Linux feasibility probe. The key-isolation safeguard now passes that
probe, but native Windows validation remains pending. No
Windows runtime support has been validated. This document is an
engineering handoff, not an installer. See [phase 3 findings](WINDOWS_PHASE3_FINDINGS.md).

| Item | State |
| --- | --- |
| Working Linux baseline | 0.4.7, `20165a8f3dda667f337ca9d73048a814d8778f18` |
| Linux checkout | `/home/small-server/Desktop/RPALLMs/jvcli`, branch `main` |
| Windows checkout | `/home/small-server/Desktop/RPALLMs/jvcli-windows` |
| Windows branch | `feature/windows-powershell` |
| Repository | `VMatee/jv-cli` — no new GitHub repository needed |
| Checkpoint | Workspace `.rollback-backups/jvcli-linux-0.4.7-before-windows-20260927T175124Z/` |
| Implemented Windows product phases | Engine tool-environment safeguard and package inventory fix; no native port |
| Next task | Run Phase 3 native Windows probe, then implement Phase 4 interfaces |

The worktree has independent checked-out files but shares Git refs and objects with
the original repository. It is not a security sandbox. Running an installer or a
command against a real home could still affect the working Linux installation.

## Supported target to establish

Start with native Windows 11 x64 and PowerShell 7. Windows PowerShell 5.1 and ARM64
are separate future targets, not implied support. Preserve the Linux command set,
API behavior, permissions, slash suggestions, English slash command names, and Thai
input/output. Use one shared codebase with explicit platform boundaries.

A local VM is not required for initial development. Windows CI can exercise offline
tests. A normal Windows user session is still required later to validate terminal,
IME, ACL, cancellation, and sandbox behavior. Linux-hosted PowerShell alone cannot
prove native Windows compatibility. Do not promise identical security until tested.

## 1. Preserve Linux baseline — complete

The checkpoint contains a verified Git bundle, a tracked-file SHA256 baseline,
and copies of the existing Linux release ZIP and checksum. It excludes installed
credentials, runtime sessions, and browser data. The original branch remains `main`.

To inspect recovery material, use `git bundle verify <checkpoint>/jvcli.bundle`.
If recovery is ever needed, clone the bundle into a new recovery directory and
compare it with the existing work. Never restore over the original checkout or
discard newer work automatically. The bundle preserves refs present at creation;
it does not back up future uncommitted changes in this Windows worktree.

## 2. Isolated worktree and handoff — complete

The branch starts at the exact Linux release commit above. README, AGENTS, this
plan, and package manifest are the preparation changes. No Python implementation,
installer, dependency, version, Linux configuration, or production service changes
are part of this phase. Do not repeat `git worktree add` when resuming.

## Resume checklist for every future agent

1. Read workspace `AGENTS.md`, this worktree's `AGENTS.md`, and this document.
2. Confirm `pwd`, `git status --short --branch`, `git rev-parse HEAD`, and
   `git worktree list`. Preserve existing uncommitted work before making changes.
3. Inspect the current source; this plan describes a baseline, not immutable code.
4. State the phase being implemented and its acceptance gate.
5. Use temporary test homes and loopback mock services with synthetic accounts.
6. Record files changed, exact commands/results, skipped checks, and next step.
7. Stop at a safety or platform blocker; never weaken permissions to make a test pass.

## 3. Compatibility inventory and engine feasibility

The exact inventory, mock probe, Linux results, native Windows recipe, and
remaining blocker are recorded in [phase 3 findings](WINDOWS_PHASE3_FINDINGS.md).

Inspect these concrete boundaries before writing the port:

| Area | Baseline source | Work needed |
| --- | --- | --- |
| Engine launch, locks, environment, cancellation | `lib/jvcli/cli.py` | `fcntl`, executable discovery, POSIX process groups, minimal environment |
| Interactive input | `lib/jvcli/slash_ui.py` | `termios`, `tty`, readline/terminal assumptions |
| Private files | `lib/jvcli/safety.py` | POSIX modes, symlink checks, Windows ACL/reparse behavior |
| Images and uploads | `lib/jvcli/images.py`, `lib/jvcli/transport.py` | Directory-FD and no-follow guarantees, no-overwrite capture |
| Installation and update | `scripts/manage.py` | Linux prerequisite gate, locks, symlinks, shell paths |
| Distribution | `scripts/build_release.py` | Linux artifact naming and platform inventory |
| Automated tests | `.github/workflows/test.yml`, `tests/` | Windows runners, PTY/POSIX-only tests |

The inspected engine pin is 0.149.1; its package metadata advertises a Windows x64
distribution. Availability in metadata does not prove integration works. Keep the
pin unless a separately justified compatibility change is reviewed.

First prove on Windows: engine starts, reaches a mock endpoint, requests a PowerShell
tool, executes it under the intended sandbox, returns tool output, and completes a
mock continuation. No real JV login or inference is needed. Record required binaries,
runtime versions, exit codes, and sandbox capabilities. Fail closed if unavailable.

The package inventory now excludes root `.git` files as well as `.git`
directories, with a regression test. Verify any direct worktree build still
contains no Git metadata, private paths, or runtime state.

**Gate:** Windows engine feasibility and sandbox contract demonstrated with mocks;
all required platform boundaries documented. If blocked, report before proceeding.

## 4. Introduce narrow platform interfaces

Implement platform-specific terminal, lock, process, path, environment, and private
file operations behind small interfaces. Preserve existing Linux behavior and tests.

- Retain shared installation locks and exclusive session locks with correct Windows
  semantics. Test competing processes and interrupted owners.
- Replace unconditional POSIX imports with explicit platform implementations.
- Use safe argument arrays; do not build commands through `shell=True` or string
  substitutions. Select PowerShell deliberately and explain its syntax to the agent.
- Preserve prompt-on-stdin handling and secret exclusion. Allow only necessary
  Windows environment variables; do not inherit the entire parent environment.
- Design owned-process-tree cancellation on Windows and test descendants. Ctrl+C
  must not automatically cancel/resubmit a remote job or replay an uncertain Send.
- Preserve traversal/no-follow protections. Windows junctions, reparse points,
  case-insensitive paths, and path races require equivalent controls, not skipped
  checks. Decide and document UNC and long-path support explicitly.

**Gate:** Linux regression suite remains green; Windows unit tests prove equivalent
behavior. Unsupported secure operations produce an actionable error.

## 5. PowerShell interaction and language support

Implement native interactive input while preserving slash command discovery,
completion, history, editing, multiline paste, EOF, Ctrl+C, and hidden passwords.
Test redirected stdin/stdout separately from interactive terminals.

Test Thai input/output and filenames, Unicode combining characters, emoji, spaces,
backticks, quoting, CRLF, and keyboard/IME behavior. Slash commands stay English.
Do not automatically rewrite arbitrary Bash commands into PowerShell strings.

**Gate:** Mock agent round trips and UI tests pass; manual Windows terminal/Thai IME
checks are recorded. Do not substitute Linux PTY tests for this evidence.

## 6. Permissions, state, and execution safety

Choose a private preview install/state namespace, for example
`%LOCALAPPDATA%\JVCLI-WindowsPreview`, independent of any existing installation.
Keep fresh test `JVCLI_HOME` directories. Do not migrate real Linux credentials.

Validate private ACLs, atomic writes, safe uploads/downloads, session locking,
workspace boundaries, read-only mode, explicit network denial, and secret isolation
in actual child processes. Test attempted writes outside the allowed workspace and
network access when denied. Preserve normal legacy and Wire transport semantics,
response/tool binding, and duplicate-submission protections.

Determine whether the pinned engine needs a separate sandbox setup/elevation step.
If so, review and document it explicitly; do not silently elevate normal execution
or bypass the sandbox. Never describe workspace selection alone as isolation.

**Gate:** Security tests pass on a normal Windows account. CI administrator context
alone is insufficient proof of normal-user sandbox behavior.

## 7. Windows package, installer, and offline CI

Add a per-user Windows launcher and installer with reviewed PowerShell entry points.
Handle missing Python/Node dependencies clearly. Preserve checksums, manifests,
licenses, upgrade rollback, active-use locks, and user-data retention on uninstall.
Avoid global profile/PATH mutations unless explicitly selected by the user.

Produce distinctly named Windows artifacts; keep Linux artifact behavior intact.
Decide a preview version before publishing. Do not relabel modified code as the
already published Linux 0.4.7 release.

Add Windows CI while retaining Linux CI. Use least-privilege workflow permissions,
mock services only, no production credentials, no automatic release or tags. A
future authorized feature-branch push can enable hosted Windows tests. Existing
tag-triggered release workflows must not be triggered during development.

**Gate:** Clean Windows installation, version/help/doctor, mocked agent execution,
upgrade, rollback, and uninstall pass in temporary locations. ZIP inventory contains
no Git pointers, credentials, sessions, or build-machine paths.

## 8. Validation and acceptance

For implementation changes, follow the contributor checks in a clean source export
until worktree packaging is fixed:

```bash
./scripts/build-release.sh
./test.sh
./verify.sh
python3 -B scripts/engine_smoke.py
python3 -B scripts/agent_smoke.py
python3 -B scripts/completion_smoke.py
git diff --check
```

Inspect each smoke script before use and run only offline/mock paths. Do not run
`live_smoke.py`, production scenarios, or real inference as routine validation.
Engine smokes require supported dependencies in isolated test storage. Record skips
honestly; do not install into the working Linux user's home to satisfy a check.

On Windows, add equivalent native commands and actual results to this document once
implemented. Test paths with spaces/Thai, malformed responses, connection failures,
timeout, cancellation, concurrent sessions, and uncertain submission without retry.
Validate full tool-call/continuation flows for both transports using mock servers.

Then perform ordinary-user Windows terminal acceptance. A separately authorized
single live request can validate integration after all offline gates pass; it is
not authorized by this plan. Preserve Linux regression evidence before any merge.

**Gate:** Both OS suites, package checks, and native Windows safety/UI acceptance
pass with documented limits. Only then propose merging and releasing for review.

## Authorization boundaries and progress record

This preparation does not authorize changing production, submitting inference,
running approved scenarios, modifying credentials/accounts, pushing, merging,
tagging, or releasing. Obtain the relevant authorization before those operations.
Future implementation should remain in this worktree with no production dependency.

After every phase, append: date, phase, commit/worktree status, changed files, exact
test command/counts, skips, manual evidence, remaining risks, and next action.

- Preparation: Linux checkpoint and isolated worktree created; documentation added.
- Windows port implementation: not started; only the engine key safeguard and
  package inventory fix were added.
- Phase 3: current-source inventory complete; Linux pinned-engine mock probe now
  passes after the key safeguard. Native Windows probe remains pending.
- Native Windows validation: not run; no Windows host or runner was used.
- Next: run native Phase 3 probe on Windows, then implement Phase 4 interfaces.

### Preparation validation

Checks ran against a temporary clean source export, excluding the linked worktree's
`.git` pointer. No installed runtime or production endpoint was used.

- `sh scripts/build-release.sh`: passed; temporary validation artifact only, not a release.
- `sh test.sh`: 330 tests, 327 passed, 3 skipped, 0 failures (36.386 seconds).
- `sh verify.sh`: passed, 79 source/documentation files.
- `git diff --check`: passed.
- Original Linux tracked-file SHA256 comparison: all unchanged.
- Original Linux checkout: clean `main`; installed launcher still reports 0.4.7.
- Checkpoint Git bundle verification and original release ZIP checksum: passed.
- Windows execution/security/UI tests: not run; implementation has not begun.
- No commit, push, release, production operation, or real inference performed.

The temporary build retains the baseline version only for package validation. Do
not distribute it as the published 0.4.7 release. The checkpoint contains the actual
original release artifact.

### Phase 3 progress — 2026-09-28

- Branch remains `feature/windows-powershell` at the Linux 0.4.7 baseline commit;
  the preparation edits remain uncommitted in this worktree.
- Added `scripts/windows_engine_probe.py` and
  [phase 3 findings](WINDOWS_PHASE3_FINDINGS.md). No CLI product code changed.
- Verified the pinned Windows x64 package metadata in the npm registry: version
  `0.149.1-win32-x64`, OS `win32`, CPU `x64`. No package downloaded here.
- Linux native engine 0.149.1 probe: 5 synthetic cases passed; the sixth failed
  because the shell tool saw the ephemeral adapter key. The first five used 10
  mock model requests and 5 shell executions, with 0 real inference requests.
  Workspace write control, outside-workspace denial, read-only denial, and
  tool-network denial passed. A separate temp-only reproduction using the actual
  Linux CLI config confirmed key presence without exposing its value.
- Native Windows engine, PowerShell, ACL, and interactive UI checks: **not run**.
  Phase 3's security and Windows gates remain open; do not mark Windows support complete.
- Next: resolve the key-isolation failure in this worktree with a mock proof, then
  run the native probe in the findings document. Preserve the original checkout.
- Temporary clean-export validation after Phase 3 edits: `sh scripts/build-release.sh`
  passed; `sh test.sh` ran 330 tests (327 passed, 3 skipped, 0 failed, 36.372s);
  `sh verify.sh` passed with 81 source/documentation files. This build is only a
  local packaging check and must not be published as the existing 0.4.7 release.
- The direct Phase 3 Linux probe exits 1 at its adapter-key isolation gate after
  five earlier cases pass. Existing tests passing does not clear that gate.

### Phase 3 follow-up — 2026-09-28

- The pinned engine 0.149.1 ignored the `exclude` list for its provider key in
  this tool path. The Windows worktree now also sets the shell tool's copy of
  `JVCLI_ADAPTER_KEY` to an empty value. The engine retains its nonempty key for
  authenticated loopback requests. The key value is never written to config.
- The six-case offline Linux native-engine probe passed: 12 synthetic model
  requests, six shell executions, no real inference. An additional mock round
  using the actual `cli._write_engine_config()` and `cli._engine_env()` passed.
  This proves only the pinned Linux engine behavior; native Windows remains open.
- `scripts/manage.py` now excludes a linked worktree `.git` file from public
  packages; `tests/test_public_release.py` covers that case. Build and package
  validation results are listed below.
- No original Linux checkout, installed CLI, production service, account, or
  runtime state was changed. The earlier failed probe remains documented as the
  regression reproduced before the safeguard.
- `python3 -B -m unittest tests.test_cli_hardening`: 33 tests, 32 passed, one
  skipped. `sh test.sh`: 330 tests, 327 passed, three skipped, zero failed.
- `sh scripts/build-release.sh`: passed in this isolated worktree after the
  `.git` pointer exclusion test. `sh verify.sh`: 81 files verified. The local
  validation ZIP checksum, Git-metadata inventory, and extracted-package
  `verify.sh` passed. This ZIP is not a published 0.4.7 release.
- `python3 -B -m py_compile` on touched Python files and `git diff --check`
  passed. Native Windows tests remain pending; the current host is Linux.

### Feature-branch publication check — 2026-09-29

- The local Linux `main` checkout and its GitHub branch match. This worktree
  remains on `feature/windows-powershell`; no merge, tag, or release was made.
- `./test.sh` passed: 330 tests, three skipped. `./verify.sh` passed. The
  local package ZIP checksum and extracted-package integrity check passed.
- An extracted package completed a temporary portable `--no-engine --offline`
  setup and reported `JV CLI 0.4.7`; its doctor check reported the expected
  missing engine. The package was not published as a 0.4.7 release.
- The pinned Linux engine 0.149.1 mock probe passed all six cases, with 12
  synthetic model requests, six shell executions, no real inference, and the
  adapter key hidden from shell tools.
- Native Windows validation and the remaining port phases are still pending.
