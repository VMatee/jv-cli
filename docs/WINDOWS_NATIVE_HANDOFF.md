# JV CLI Windows native development handoff

This engineering handoff was prepared on Linux on 2026-10-01 and continued on
native Windows the same day. **Native Windows JV CLI is not functional or accepted
yet.** Private NTFS state and kernel locks now have native tests; execution and
packaging remain blocked. Do not distribute this branch as a supported release.

## Public-file policy continuation — 2026-10-01

Published the two existing commits through the configured repository deploy-key
remote, then fetched and verified local/origin both equal
`d2ca75d00b3b8c9e9a225510a847a81b0e1735ec`. The previous publication failure is
resolved. [CI run 36878979016](https://github.com/VMatee/jv-cli/actions/runs/36878979016)
passed both Windows jobs and all four Linux Python jobs (3.10 through 3.13).

`atomic_write(..., 0o644)` now creates a protected user/LocalSystem full-access
DACL plus Everyone read access. Existing public files and their containing
directory may have inherited ACLs, but their owner must be the user, LocalSystem,
or Administrators, and no other effective grant may allow writes, deletion,
permission changes, or unknown rights. Unsupported ACEs fail closed. Private
reads/writes retain their stricter protected-DACL policy and reject public files.
Public replacement uses the same pinned-parent, no-reparse, hard-link rejection,
flush, rename, and cleanup implementation. It does not alter the parent ACL.
The native `open_public_read` helper retains a verified readable handle for later
engine/package validation. This is a filesystem primitive, not an installer.

`py -3.10 -B -m unittest discover -s tests -p test_windows_native.py -v`:
37 native tests passed. Added public new/existing/replacement cases, trusted
inherited ACLs, unsafe parent/file write grants, junction/hard-link rejection,
failed replacement preservation, and unsupported modes. Restricted-token checks
prove private read denial and public read-only access at the Windows kernel.

## Native Windows storage checkpoint — 2026-10-01

Starting checkout: `008eb5eee246a808794ffa8e1a70f018d4965514`, clean
`feature/windows-native`, matching freshly fetched origin. Actual host: Windows
11 Pro, build 26200, AMD64; Python 3.10.11, Git 2.49.0.windows.1, Node 22.12.0,
Windows PowerShell 5.1.26100.9549. The test process token was **not elevated**.
No additional Windows user, administrator privileges, real account, production
authentication, external inference, or JV job was used.

Implemented in the lazy native binding `platform/_windows_fs.py`, exposed through
the existing `windows.py` boundary:

- Private directories and files receive a protected DACL at creation, with full
  access for the current token's user and LocalSystem only; owner and every ACE
  are checked on the opened handle. Existing inherited, null, extra-principal,
  inherit-only, or otherwise unsupported DACLs are rejected without repair.
- Every component is opened with `NtCreateFile` relative to a retained parent
  handle, using `OBJ_DONT_REPARSE` and `FILE_OPEN_REPARSE_POINT`. Directory handles
  include list access and deny delete sharing to prevent ancestor renames.
  Handle inspection rejects reparse points and multi-link state files. A real
  injected junction mutation after opening the parent did not redirect a write.
- UTF-8 private replacement writes a uniquely created private file, flushes it,
  then uses handle-relative `NtSetInformationFile` rename. Failures preserve the
  previous file and mark only the owned temporary handle for deletion. A live
  reader can cause a sharing failure; the operation fails closed without retry.
  This proves atomic visibility and explicit flushing, not power-loss recovery.
- `LockFileEx` locks byte zero with immediate shared/exclusive contention.
  Opaque owners retain non-inheritable file and ancestor handles; closing or
  process termination releases the kernel lock. No metadata or sentinel-file
  interpretation can override a live conflicting owner.

Security scope is **fixed local NTFS volumes**. UNC, other filesystems, substituted
drive roots, alternate streams, reserved names, and ambiguous components are
rejected. Private state permissions do not isolate another process running as the
same user or an administrator. Kernel access denial was additionally exercised
with an impersonated restricted token; a separate Windows account was not created.
The path checker returns a point-in-time lexical path; it is not a capability for
later unchecked filesystem operations. Sensitive backend operations reacquire
handles. Workspace/image/download containment remains a separate unfinished layer.

Rejected approach: Win32 metadata-only directory handles plus sharing flags did
not prevent write/reparse mutation. Adding list access blocked ordinary path-based
replacement. The implementation instead opens and renames relative to pinned
handles; it does not relax sharing or substitute zero-valued no-follow flags.
Native API references: [NtCreateFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile),
[OBJECT_ATTRIBUTES](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes),
[FILE_RENAME_INFORMATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information),
[LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex).

Native checkpoint commands (Python launcher `py -3.10 -B`):

| Command suffix | Result |
| --- | --- |
| `scripts/windows_preflight.py` | 91 shared/preparatory tests passed, zero skips; 59 Python files compile; imports/version pass |
| `-m unittest discover -s tests -p test_platform_contracts.py -v` | 21 passed at the initial baseline; included in the final preflight/broad gate |
| `-m unittest discover -s tests -p test_windows_native.py -v` | 30 actual native tests passed, zero skips |
| `scripts/windows_native_tests.py` | 121 passed: 91 shared + 30 native storage/locking tests, zero skips |
| `bin/jvcli --version` | JV CLI 0.4.9 |
| `scripts/manage.py verify` | Complete manifest verified: 104 source/documentation files |

The native tests include new/existing directories and files, replacement, failure
cleanup, Thai/Unicode/spaces, long paths, case aliases, inherited ACL rejection,
restricted-token read denial, hard links, junctions, a reparse mutation race,
non-inherited handles, competing writer/reader processes, process death, corrupt
metadata, missing `create=False` locks, and exception cleanup.

CI adds a separate Windows native-state job; the existing Windows preflight and
Linux matrix remain intact. Hosted results must be checked after push. Linux-only
tests are not relabeled as native Windows acceptance. `.gitattributes` now fixes
text checkout line endings to LF so source manifest hashes agree across platforms.

Implementation commit: `086bd53272370c860c83706f22a7d89703958095`. Publication was
attempted normally but the configured HTTPS account `mateelonggpt-dev` received
HTTP 403 (no write access to `VMatee/jv-cli`). A read-only SSH attempt with
`BatchMode=yes` and existing host trust failed with `Permission denied (publickey)`.
No credentials, keys, authentication settings, or remote URLs were changed.
Fresh fetch still reports `008eb5eee246a808794ffa8e1a70f018d4965514` on origin;
local and remote SHAs therefore do **not** match. Repository write authentication
must be fixed before publication. The available [GitHub Actions run](https://github.com/VMatee/jv-cli/actions/runs/36864280861)
succeeded for the starting SHA only; it supplies no CI evidence for this checkpoint.
The implementation and this evidence follow-up are committed locally. No Windows
ZIP, installation, engine acceptance, or bridge execution acceptance was performed.

Remaining: public-file `0o644` ACL policy is explicitly unavailable; existing
private storage must match the protected policy, with no migration/repair utility
yet. Engine discovery, restricted environment, owned process trees, bounded bridge
pipes, deadlines, workspace containment, console, installer and Windows packaging
remain unimplemented. `require_bridge_io` still prevents ready. No Windows artifact
or installed-package/real-engine acceptance is claimed. The Linux shell build,
test and verification gates remain Linux CI tasks; they are not a Windows builder.
Continue with the public-file policy and native engine/runtime layers, preserving
the version 0.4.9, engine 0.149.1, and protocol 1 pins.

## Current baseline

| Item | Value |
| --- | --- |
| Product/repository | JV CLI, `VMatee/jv-cli` |
| Freshly fetched `origin/main` | `b891df33365080af9ff587d69d74a434b79087ba` |
| Development branch | `feature/windows-native`, created from that `origin/main` |
| Tested platform preparation branch SHA | `9717fbb79a61d6e65d10a85299e8a9ef51e47d97` |
| Handoff checkout SHA | Run `git rev-parse HEAD`; the documentation commit follows the preparation SHA above |
| Previous Windows branch SHA | `e5f722f7a319a9e3a9185f1a3e977301947deaf2` (`feature/windows-powershell`) |
| Canonical `VERSION` | `0.4.9` (unchanged) |
| Public bridge command/protocol | `jvcli bridge --stdio`, protocol **1** |
| Pinned Codex engine | `0.149.1` (`cli.ENGINE_VERSION`, not upgraded) |
| Existing Linux offline Node pin | `24.21.0` (`scripts/build_offline_release.py`) |

After fetching, compare `git rev-parse HEAD` with
`git rev-parse origin/feature/windows-native` and record the actual SHA before
continuing. Later Windows commits may legitimately advance this branch; preserve
them. Do not treat this document's preparation SHA as a reason to replace work.

The Linux preparation used the existing clean linked worktree at
`/home/small-server/Desktop/RPALLMs/jvcli-windows`. The stable `jvcli/` worktree
remains on main. They share Git objects, refs, and SSH origin, not checked-out
files. The older Windows branch remains preserved. A fresh Windows clone needs
only this repository; the Linux parent workspace and sibling products are not
dependencies. JV Desktop 0.1.1 Linux is outside this task and was not changed.

## Architecture and preparation changes

One product, one source tree, one bridge core. Shared code retains authentication,
JV API transport, strict JSON, NDJSON schemas, session metadata, request/turn IDs,
event normalization, prompt handling, permission selection, redaction, and error
schemas. `bridge.py` is shared; there is no Windows bridge fork.

| File/symbol | Preparation and rationale |
| --- | --- |
| `lib/jvcli/platform/__init__.py::get_backend` | Lazy POSIX/Windows dispatch; unknown OS produces an actionable error. `state_directory` selects a location without creating it. |
| `platform/posix.py` | Extracted existing private directory/file operations, no-follow reads, nonblocking shared/exclusive `flock`, engine discovery, argv spawn, process-group cleanup, and signal deadlines. Linux modes/flags, timeouts, lookup order, and environment remain the same. Spawn explicitly sets `shell=False`. |
| `platform/windows.py` | Matching operation signatures and `PlatformUnavailableError` stubs; no chmod substitute, unlocked writer, fake cancellation, or insecure fallback. |
| `platform/common.py` | Pure Windows state-path and executable-name contracts. Drive/UNC syntax, ambiguous state names, and reserved names are checked lexically; this is not native containment or ACL validation. |
| `safety.py` | Existing public helpers delegate native filesystem operations. JSON parsing, size/type validation, redaction, and terminal hygiene stay shared. |
| `cli.py` | State selection, engine lookup/spawn/stop, and session/install locks use the boundary. `_engine_command` extracts the unchanged argv construction; `_run_engine` still writes the prompt to stdin. Windows public bridge startup fails before announcing ready until native pipe transport is implemented. |
| `bridge.py::deadline` | Delegates the OS deadline mechanism; all bridge validation, schemas, lifecycle, and event semantics are unchanged. |
| `slash_ui.py::read_interactive_task` | POSIX terminal imports are lazy and guarded; normal Linux palette/readline behavior remains. This is not a Windows console implementation. |
| `scripts/manage.py` | Uses the same lock boundary; excludes linked worktree `.git` files from packages. Install/update logic remains Linux-only. |
| `tests/test_platform_contracts.py` | 21 portable tests: state paths, naming, dispatch, explicit unsupported errors, shared protocol/permissions/events, and argument construction. They make no native Windows security claim. |
| `tests/test_platform_posix.py` | Four actual POSIX checks, including competing process locks, permission modes, Unicode stdin, and owned process-group creation. |
| `tests/test_public_release.py` | Reused the old branch's worktree-pointer inventory regression. |
| `scripts/windows_preflight.py`, `.github/workflows/test.yml` | Compile all source/test Python without caches, import shared modules/package helpers, check version, and run 91 explicitly selected shared/preparatory tests. Windows CI uses Python 3.12 on `windows-2022`; Linux CI remains intact. No native execution/package acceptance is implied. |

`README.md` and released Linux customer documentation were not rewritten to
advertise Windows. The Linux release workflow, dependencies, and version stay
unchanged. Local Linux ZIPs built for validation are not published releases.

## Original handoff gaps (see native checkpoint above for completed portions)

Implement one boundary at a time with real native tests. Do not change stub
guards to return success while their guarantees are missing.

1. **Private storage and path security:** implement `no_symlink_path`,
   `private_dir`, `atomic_write`, and `open_private_read` in `windows.py`.
   Verify ownership/ACLs and safe replacement on existing directories/files too.
   Keep shared `read_private_json` size/type/corrupt-JSON handling. Public manifest
   mode `0o644` and private state mode `0o600` need distinct Windows policies.
2. **Locks:** implement `open_lock`, `lock_file`, and `close_lock`. Handles are
   opaque to callers; reads/writes of session metadata must retain a single
   conflicting owner. Shared install locks coexist during sessions; install,
   update, and uninstall acquire exclusive locks. Contention raises
   `BlockingIOError`, never silently permits a writer. `create=False` never
   creates a file. Test process death, independent competing processes, stale
   locks, corrupt metadata, and exceptions during acquisition/cleanup.
3. **Native engine and process ownership:** implement `find_engine`,
   `spawn_engine`, and `stop_process`. Preserve the process API used by
   `_run_engine` (`stdin/stdout/stderr`, `pid`, `poll`, `wait`) or adapt it cleanly.
   Own the local tree before untrusted children can run; retain handles for
   cleanup after the parent exits. Do not inherit arbitrary handle/env state.
4. **Environment/config:** `_minimal_env`, `_diagnostic_env`, `_engine_env`, and
   `_write_engine_config` still express Linux HOME/TMPDIR/XDG tool isolation.
   Add native equivalents through the platform layer: required Windows system
   variables, private USERPROFILE/APPDATA/LOCALAPPDATA/TEMP/TMP, and necessary
   PATH entries. Do not copy the entire parent environment. Prove the pinned
   engine and its tools cannot load normal-user credentials/config or see the
   adapter key/password/token. Keep sandbox permissions enforced by the engine.
5. **Bridge pipes/deadlines/control events:** `bridge_io.py` still uses
   `select.select` on pipe FDs, nonblocking FD writes, and a bounded writer.
   Implement native pipe primitives behind the shared framing/queue core;
   Windows socket select is not a pipe implementation. Preserve UTF-8 byte
   framing, EOF/final-line handling, 256 KiB input and 128 KiB event limits,
   64-event writer queue, and 5-second write timeout. Set appropriate binary
   pipe modes and handle CRLF without corrupting frames. Implement
   `windows.deadline` without an auth/logout worker mutating state after timeout;
   POSIX `SIGALRM/setitimer` has no Windows substitute here. Review
   `bridge.serve` SIGINT/SIGTERM handling. `require_bridge_io` must stay blocked
   until startup/shutdown, cancellation, backpressure, and deadlines work.
6. **Workspace identity and safe file operations:** `_workspace_check` still
   expresses POSIX root/home/project-config checks. Establish native drive/UNC
   roots and canonical workspace identity for resume without changing the
   metadata schema. `images.py::snapshot_images` and
   `transport.py::submit_job`/`download_response_files` still use `O_NOFOLLOW`,
   `O_DIRECTORY`, directory FDs, or no-overwrite links. Replace those OS
   primitives safely; keep the shared image/API logic. Do not replace no-follow
   with zero-valued flags or weaken containment to string-prefix comparison.
7. **Console:** implement Windows input/palette primitives instead of the
   guarded termios/tty/readline path, including Thai IME, Unicode editing,
   multiline paste, hidden passwords, Ctrl+C, EOF, and redirected streams.
8. **Install/update/package:** implement native per-user install/launcher,
   prerequisite checks, manifest validation, upgrade/rollback/uninstall, active
   use locks, and data retention. `manage.py` still contains Linux prerequisites,
   `geteuid`, `.local`, symlink launchers, chmod and bashrc handling. Shell entry
   scripts and both release builders still target Linux. Imports alone do not
   make these Windows installers.

The audit also checked hard-coded `/tmp` and `/dev/null`, executable bits, PATH
splitting, socket use, and separators. The adapter uses loopback TCP, not a
Unix-only API socket. PATH splitting in `manage.py` already uses `os.pathsep`;
there is no reason to invent another PATH parser. `/tmp` guidance in
`protocol.BASE_AGENT_INSTRUCTIONS` and Bash-oriented smoke fixtures need Windows
wording/fixtures after native engine behavior is established. Live/browser
smoke scripts are not development gates and must not be run against production.

## Native security and state contract

Normal Windows state is intended at `%LOCALAPPDATA%\JV\jv-cli`. An absolute
`JVCLI_HOME` overrides it exactly, so JV Desktop can supply isolated state.
The pure selector creates nothing, rejects relative/drive-relative/device state
paths and unsafe filename components, and requires LOCALAPPDATA or the explicit
override. It does not fall back to a project workspace. Native privacy remains
unimplemented. Linux keeps its existing `APP_ROOT/.state` default and expanded,
absolute `JVCLI_HOME`; XDG variables currently concern the private tool cache,
not a new Linux state migration.

Investigate the Windows known-folder API for reliable user-data discovery;
validate the supplied environment override using the same secure path contract.
The LocalAppData location is documented in Microsoft's
[known folders reference](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid).
Desktop and terminal state must remain independent when an override is supplied;
never copy real credentials or sessions into tests or project directories.

Candidate native mechanisms, to validate on Windows rather than assume:

- **Privacy:** create and inspect an appropriate user-private DACL and owner,
  with only deliberately allowed system identities. `chmod(0o600)` is not an
  ACL proof; inherited permissions need review. Microsoft documents security
  descriptors at creation and inherited default ACLs in
  [file security](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights).
- **Locks:** investigate `LockFileEx` shared/exclusive locks with immediate
  contention reporting and handle lifetime ownership. Its
  [documented flags](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)
  support that contract; actual competing-process, crash, and filesystem tests
  are still required. An existence-only sentinel is insufficient.
- **Local process trees:** investigate a private owned Job Object, deliberate
  inheritance/breakaway policy, and safe assignment before execution. Job
  membership and kill-on-close semantics are documented in
  [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
  Test interaction with the engine's own sandbox/jobs, CI jobs, parent exit,
  grandchildren, and unrelated sentinel processes. CTRL_BREAK may be a graceful
  option for an owned console group; it is not a complete cleanup mechanism.
- **Paths:** test actual handles and ancestor containment across drive letters,
  case aliases, spaces, Unicode/Thai filenames, long-ish paths, UNC shares,
  reserved names, alternate streams, and junction/symlink/reparse races. The
  [Windows naming rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
  and [reparse points](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points)
  describe issues beyond lexical parsing. Decide supported UNC/long-path scope
  explicitly; reject anything lacking verified privacy/locking/containment.

Lexically accepting a UNC path in a unit test does not accept that filesystem
for private state. Case-preserving path tests do not prove native file identity.
Run physical path/ACL/locking tests as an ordinary Windows user. Administrator
CI runners and WSL/Linux results cannot establish those guarantees.

Critical invariants:

- User prompts travel over bridge stdin as NDJSON and engine stdin as task data.
  Never put them into shell strings, argv, `powershell -Command`, `cmd.exe /c`,
  or `shell=True`. The target is `JV Desktop.exe` → native argv spawn of
  `jvcli.exe bridge --stdio` → stdin/stdout NDJSON, protocol 1.
- stdout contains protocol events only; diagnostics go to stderr. Preserve
  request IDs, sanitized errors/events, prompt limits, and memory-only bridge
  authentication. Never log/store passwords, API tokens, adapter keys, or child
  environment dumps. Keep credentials outside project workspaces.
- Keep read-only/network-denial semantics, session binding, corrupt-state
  recovery, workspace containment, secret redaction, and no uncertain replay.
  Selecting a directory is not a sandbox or a permission guarantee.
- Cancellation is **local cancellation; remote job state may remain unknown**.
  Terminate only owned local children. Never use process-name kills such as
  `taskkill /IM python.exe` or `taskkill /IM node.exe`; do not cancel or resubmit
  remote work implicitly.

## Old branch review: keep / drop / migrate

The old branch contains one unique checkpoint after 0.4.7 (`20165a8...`). It
predates 0.4.8 offline packaging and the two bridge implementation/hardening
commits released with 0.4.9. It did not implement a native Windows product or
duplicate the whole product tree, and is not this branch's base.

| Decision | Evidence and handling |
| --- | --- |
| Migrated | `manage.EXCLUDED_FILES` excludes a root worktree `.git` pointer; its public-inventory/manifest regression was reused. This is independent of OS and necessary for safe worktree builds. |
| Kept as reference | Compatibility inventory and six synthetic engine cases: read, allowed workspace write, denied outside write, read-only denial, tool network denial, adapter-key exclusion. Recreate native tests using the actual shared CLI configuration and pinned engine. |
| Not copied | `windows_engine_probe.py` repeats TOML/model catalog/config/env logic and hardcodes the pin. Its synthetic PowerShell `-Command` strings are tool fixtures, not prompt-bearing JV CLI launch code. They are not a design for normal bridge execution. Timeout handling uses PID-scoped `taskkill /T`; that lacks the retained ownership proof required for the new process contract. |
| Separate finding | The old branch overrides the tool's `JVCLI_ADAPTER_KEY` with an empty value after finding that `exclude` alone was insufficient in its pinned Linux probe. That change is absent from current main and was not reapplied in this preparation, which preserves released Linux security behavior. Preserve the finding and require a real native secret-isolation regression with product config; a failed gate needs a focused fix, not copied probe success. |
| Obsolete | 0.4.7 checkpoint/version gates, PowerShell-named branch as canonical target, pre-bridge sequencing, old Linux checksum/inventory counts, and a separate Windows-preview product namespace. Use one JV CLI product, this baseline and branch, and disposable state for tests. |

Inspect historical evidence without merging it wholesale:

```text
git show origin/feature/windows-powershell:docs/WINDOWS_PHASE3_FINDINGS.md
git show origin/feature/windows-powershell:scripts/windows_engine_probe.py
git diff 20165a8 origin/feature/windows-powershell -- lib/jvcli/cli.py scripts/manage.py
```

## Required Windows environment and runtime strategy

Initial candidate target is an ordinary-user Windows 11 x64 PC; this is a
development target, not a support claim. Inspect actual edition/build/architecture.
Git and Python **3.10+** are needed for source/preflight. Python 3.12 is the
hosted Windows preflight version. No JV CLI source build requires Rust: this
repository uses Python and a prebuilt pinned engine. Rust would be relevant only
to a separately chosen upstream/native component build.

Existing normal Linux installation requires Node **18+** and npm, installs
`@openai/codex@0.149.1` into private `runtime`, and launches its `.bin/codex`.
The Linux offline ZIP bundles Node **24.21.0**, `@openai/codex`, the pinned
Linux-x64 native package, a shell wrapper, checksums, and licenses. Its Node SHA
and Linux native paths cannot be reused for Windows binaries.

On Windows, verify the pin's actual win32-x64 package/version, native `codex.exe`
location, required DLLs, and sandbox capabilities from upstream package metadata
and the real installed engine. Old findings recorded Windows-x64 npm metadata;
they did not prove Windows execution. Prefer the verified native executable;
if Node is required, use explicit `[node.exe, absolute_codex_js, ...]` argv via a
reviewed launcher and adapt discovery/version checks consistently. Do not launch
an npm `.cmd` shim through a shell. Keep engine 0.149.1 unchanged.

Inspect installed PowerShell versions for engine tool tests. PowerShell 7 was
the old probe's candidate tool/installer environment; preflight itself needs
neither Node nor PowerShell 7. Decide and record installer-script requirements
from the implementation. Do not require a shell for prompt transport.

Eventually build `jv-cli-<version>-windows-x86_64.zip` on Windows, with an optional
offline variant and stable `jvcli.exe` launcher. No Windows builder, installer,
runtime download, package, or release was produced on Linux. Future packaging must
verify the chosen Windows Node archive's own checksum and engine package integrity,
record the resolved pins/lock data, preserve all licenses/notices, verify complete
source/runtime manifests and ZIP checksums, reject unsafe archive paths, and
exclude `.git`, credentials, sessions, runtime logs and machine-specific evidence.
Prepare in a staging directory, enforce active-use locks, retain the prior runtime
for rollback, and test failed upgrade recovery without deleting user state.

## Windows acceptance sequence

1. **Clone only this product.** Use your normal Git authentication; do not copy
   the Linux deploy key or credential state. For example:

   ```powershell
   git clone --branch feature/windows-native https://github.com/VMatee/jv-cli.git
   Set-Location jv-cli
   git switch feature/windows-native
   git status --short --branch
   git rev-parse HEAD
   git remote -v
   ```

2. **Read rules/baseline.** Read `AGENTS.md`, this handoff and
   `docs/BRIDGE_PROTOCOL.md`. Inspect local history/diffs/untracked files before
   fetching; preserve any local work. Record fetched branch SHA and upstream.
3. **Inspect the real OS/environment.** Confirm native Python, Git, and eventual
   engine tools. Record versions, not credential/environment dumps:

   ```powershell
   python -B -c "import os,platform,sys; print(os.name,sys.platform,platform.machine()); print(sys.version)"
   git --version
   $PSVersionTable.PSVersion
   Get-Command python,node,npm,pwsh,powershell -ErrorAction SilentlyContinue
   ```

   Require `nt`/`win32` for native acceptance. WSL is a Linux regression host.
4. **Run safe initial tests.** No installation or account is needed:

   ```powershell
   python -B scripts/windows_preflight.py
   python -B -m unittest discover -s tests -p test_platform_contracts.py -v
   python -B bin/jvcli --version
   ```

   Windows bridge invocation currently returns a clear unsupported error and
   no ready frame. Keep that expected behavior until its OS dependencies work.
5. **Implement one layer at a time.** Follow the gaps above. Add actual Windows
   ACL, competing-process lock, containment, owned-tree, pipe and console tests.
   Keep the portable preflight's explicit coverage honest; preserve Linux CI and
   run Linux regression for changes touching shared code before merge.
6. **Offline fake engine and services first.** Add a native Python fake-engine
   launcher using explicit argv (existing fixtures use POSIX shebang/select).
   Test startup, sessions/resume, two turns, malformed events, timeouts, uncertain
   results, request IDs, secret exclusion, Ctrl+C/EOF, cancellation, and pipe
   backpressure against synthetic loopback clients. Then test the real pinned
   Windows engine against scripted model replies and prove native sandbox/secret
   gates. Existing `engine_smoke.py`, `agent_smoke.py`, `completion_smoke.py` need
   Windows fixtures/OS handling; do not just run their Bash fixtures unchanged.
7. **Package on Windows.** Implement and document native build commands, then
   build/check ZIP manifests/checksums and licenses. No working Windows builder
   command exists in this milestone; do not label a Linux ZIP as Windows.
8. **Install into disposable user state.** Run the new documented native
   installer in a disposable per-user location. Example test namespace:

   ```powershell
   $jvTrial = Join-Path $env:LOCALAPPDATA ("JV\native-test-" + [guid]::NewGuid().ToString())
   $env:JVCLI_HOME = Join-Path $jvTrial "state"
   ```

   The native installer must create/verify private ACLs before state use. Test
   version/help/doctor, both default and isolated state selection, upgrade,
   failed upgrade/rollback, active locks, uninstall with and without retained
   state, offline installation with downloads disabled, and physical path cases.
9. **Installed bridge ready/shutdown.** A test driver must spawn installed
   `jvcli.exe` with `['bridge','--stdio']`, `shell=False`, UTF-8/binary pipes.
   Assert protocol-1 ready/shutdown/EOF and clean exit before any real login.
10. **Installed fake auth/session/turn/cancel.** Use synthetic accounts and
    loopback fixtures only. Assert prompt is absent from argv, passwords/tokens
    never appear in stdout/files/tool env, locks prevent conflicting writers,
    owned descendants die, unrelated processes survive, and permission flags
    enforce their guarantees. Test Thai paths/input and ordinary-user ACLs.
11. **Controlled production acceptance last.** Only after every offline gate
    passes, propose a separately authorized minimal real-service acceptance.
    This handoff authorizes no production login/job. Do not merge main before
    offline acceptance, or release/tag/bump versions without authorization.

## Linux preparation validation

Host: Linux x86_64, Python 3.10.12. External networking was isolated with
`bwrap --unshare-net --bind / / --dev-bind /dev /dev --proc /proc`; loopback
remained available for synthetic mock servers. The first full run encountered
four stale-manifest installation errors; the required build regenerated the
manifest, and the corrected full run passed.

| Gate | Result |
| --- | --- |
| `python3 -B -m unittest discover -s tests -v` in isolated network | 402 run, 399 passed, 3 explicit existing skips, 0 failures/errors |
| `./test.sh` in isolated network, including the handoff files | 402 run, 399 passed, the same 3 explicit skips, 0 failures/errors |
| Existing bridge suites within the full run | 46 passed, including process-tree cancellation, bounded output, signals, deadlines, hostile prompt stdin, and redaction |
| New portability/POSIX tests | 21 portable contracts + 4 native POSIX regressions passed |
| `python3 -B scripts/windows_preflight.py` on Linux | 91 selected tests, 0 skips/failures; compile/import/version passed |
| Pinned Linux `engine_smoke.py` with temporary `JVCLI_HOME`, explicit engine and isolated network | Passed all 14 checks; scripted model replies only |
| Pinned Linux `agent_smoke.py` / `completion_smoke.py` with the same isolation | Passed 8 / 16 logical rounds; no live inference |
| `./scripts/build-release.sh` / `./verify.sh` | Passed; 100 public source/documentation files, Git metadata and runtime state excluded |
| ZIP checksum, extraction, extracted `verify.sh`, disposable portable `--no-engine --offline` install and version | Passed; temporary installed command reports 0.4.9; doctor exits 1 as expected for the missing engine |
| Shell syntax and `git diff --check` | Passed |

The three standard-suite skips are Python 3.10's unavailable `tomllib`, and two
explicit real-engine/fixture-dependent integration tests. Relevant pinned-engine
mock integration scripts were run separately; a skip is not Windows evidence.
Keep `MANIFEST.sha256` synchronized after any file edit; build before tests that
install from the source manifest. Repeat these gates when native/shared code is
changed, without consuming real service scenarios for routine publication checks.

Windows CI is an explicitly limited import/shared-contract preflight, not the full
Linux suite silently skipped into green. Its hosted result must be inspected in
Actions after publication. No native Windows product acceptance was performed
during this Linux handoff. Record subsequent native results and remaining gaps
here; preserve historical findings and never substitute mocks for OS proof.

## Windows Codex continuation prompt

Copy this into a fresh Codex session on the Windows PC:

```text
Continue the official JV CLI native Windows development in VMatee/jv-cli only,
on feature/windows-native. Read AGENTS.md, docs/WINDOWS_NATIVE_HANDOFF.md and
docs/BRIDGE_PROTOCOL.md first. This is one shared JV CLI product, not a new
Windows repository. Do not modify JV Desktop or sibling products.

Inspect status, branch, HEAD, upstream, remotes, worktrees, history, diffs, staged
and untracked files before fetching. Preserve all local work. Do not blindly
pull/reset/rebase over it, force-push, recreate branches, or merge the old
feature/windows-powershell branch. Record actual baseline and branch SHAs.

Verify this is native Windows (os.name=nt, sys.platform=win32), inspect OS/build,
architecture, Python/Git/tool versions, and run python -B scripts/windows_preflight.py.
Its green result proves only imports/shared contracts. Implement real Windows
ACL/private files, lock ownership, engine discovery/environment, owned process
trees, bounded bridge pipes/deadlines, path/containment, console, and packaging
one layer at a time. Read each stub contract and add real native tests before
enabling it. Do not weaken guards or skip security/core tests to claim support.

Preserve Linux behavior and shared auth/API/session/turn/permission/redaction/
event semantics. Keep bridge --stdio, protocol 1, VERSION 0.4.9 and engine 0.149.1
unless separately authorized changes become necessary. No bridge_windows copy.
Spawn native executable argv with shell=False; prompts stay on stdin, never in
PowerShell/cmd strings or argv. Kill only owned local trees; remote job state may
remain unknown. Preserve workspace containment, read-only/network denial, secrets,
session consistency and no replay of uncertain submissions.

Use synthetic accounts, offline fake engines and loopback model fixtures first;
then the pinned native Windows engine with scripted replies. Use disposable
private JVCLI_HOME and ordinary-user state, never real credentials/project state.
Do not contact production during implementation or run real JV jobs. Do not
download a runtime merely to relabel it: verify pins/checksums/platform packages.
Build/install Windows packages on Windows only, then test installed ready/shutdown,
fake sessions/turns/cancellation, rollback and uninstall. Record commands, OS,
counts, skipped checks and physical Windows security evidence in the handoff.

Keep Linux regression green before publication of shared changes. Do not merge
main until offline acceptance passes. Merging, production acceptance, version
bumps, tags and releases require separate authorization. Work autonomously and
conserve quota; do not redo the released Linux bridge/security implementation.
```
