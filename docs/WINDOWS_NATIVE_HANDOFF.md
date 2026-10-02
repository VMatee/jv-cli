# JV CLI Windows native development handoff

## Windows package / installer checkpoint - 2026-10-02

Started clean on `feature/windows-native` at local/fetched origin
`3b02ce8f086b10dfa4a540cf9a25c2dc213e212b`. Its six CI jobs were verified green:
Windows shared/native and Linux Python 3.10 through 3.13. No runtime authority, version,
engine pin or bridge protocol change was needed for packaging.

### Distribution and installation

`scripts/build_windows.py` builds on native Windows only. It verifies the source
manifest, obtains exact SHA256-pinned official Python 3.10.11 AMD64 embedded,
Codex 0.149.1 Windows native npm and Inno Setup 6.4.3 artifacts, and rejects unsafe
archive paths. The Inno installer download was also Authenticode-verified locally
(Valid, Pyrsys B.V.). Inno is extracted using its upstream `/PORTABLE=1` support
into a disposable repository build directory; no build-tool registration/service
or machine policy changes are required. Pins/URLs are in the builder. References:
Python's official `3.10.11/python-3.10.11-embed-amd64.zip`, npm's exact
`@openai/codex/-/codex-0.149.1-win32-x64.tgz`, and upstream Inno `is-6_4_3`
`setup.iss`/`isportable.iss`. No latest/runtime download or npm invocation.

Directory bundle: `jvcli.exe`, `bin/jvcli`, `lib/jvcli`, `python/`,
`runtime/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/`,
licenses, version/build metadata and `PACKAGE.sha256`. Python `_pth` isolation
excludes site/user packages, PYTHONPATH and PYTHONHOME. The small C# AMD64 launcher
is compiled with Windows' Framework compiler; Windows' inbox .NET Framework 4.x
is used, without an extra runtime installer. It invokes the bundled Python by
absolute path with explicit argv and inherited standard handles, never a shell.
The native architecture check rejects ARM64/emulation. Its non-inherited
kill-on-close Job Object is assigned at CreateProcess using JOB_LIST; only three
standard handles are inherited. Launcher death therefore also owns/ends Python,
auth workers and nested engine/tool jobs. An application use lock remains held
through job closure. Prompts and credentials keep their existing stdin channels.

Inno setup is per-user (`PrivilegesRequired=lowest`), AMD64 Windows only, default
`%LOCALAPPDATA%\Programs\JV CLI`. State stays `%LOCALAPPDATA%\JV\jv-cli` or
absolute `JVCLI_HOME`. Setup adds only its optional user PATH entry and records
ownership. Reinstall/upgrade and uninstall require exclusive use-lock acquisition;
they never terminate applications. Failed file replacement uses Inno rollback.
Root/ancestor and nested reparse points are rejected. Unrelated nonempty install
directories and default state ancestors/descendants are rejected. Uninstall uses
its exact installed-file inventory, never recursive state deletion; unknown files
are retained. It removes only the PATH entry it owns, retaining concurrent other
entries and restoring the original string when unchanged. No remove-data option.

Artifacts: `dist/jv-cli-0.4.9-windows-x86_64.zip`,
`dist/jv-cli-0.4.9-windows-x86_64-setup.exe`, `dist/SHA256SUMS.txt`.
These are unsigned development artifacts, not releases. The payload manifest
covers 78 files including Python/Codex/Inno licenses. BUILD.json records dependency
hashes and the source-manifest hash. Fixed ZIP entry timestamps and explicit file
inventory are used; compiler/installer metadata means bit-identical builds are
not claimed. A later signing step must precede final artifact hashing.
No tests, source checkout, credentials, caches or machine evidence are shipped.

### Native acceptance evidence

`windows_package_acceptance.py` installs in a disposable protected repository
fixture with spaces/Thai paths. It refuses to replace a pre-existing user install.
It removes external Python/Codex/Node from runtime PATH and poisons PYTHONHOME and
PYTHONPATH. Public app invocations use installed `jvcli.exe`; a second test runner
uses embedded Python and checks all 19 loaded JV module origins under the installed
application. Only test fixture code comes from the checkout. Node is an explicit
network-test fixture, not a bundled/runtime dependency. Bundled Python itself is
used for tool, auth-helper and child/grandchild tests.

Seventeen installed tests, zero skips: 12 public/real-engine bridge cases (including
six socket cases in one matrix) and five direct native auth deadline races. They
cover startup, protocol 1, auth/logout, two turns, restart/resume, full-access and
approval-never settings, workspace/outside writes, secret exclusion, locking,
corrupt metadata/workspace binding, Unicode/Thai, EOF, broken output, backpressure,
cancellation/shutdown/EOF/parent-death owned cleanup, unrelated sentinel survival,
structured journal continuation/reopen and explicit restricted-request rejection.
All six PowerShell/bundled-Python/Node IPv4/IPv6 loopback connections succeeded.

Installer acceptance also passes: absolute executable/version/help/doctor, bundled
engine discovery, PowerShell 5.1 PATH invocation, hidden real-console Ctrl+C and
Thai NDJSON, active-use upgrade/uninstall refusal, forced mid-upgrade failure and
rollback (full prior manifest still valid), same-version reinstall, install/uninstall
junction rejection, portable ZIP extraction/manifest/version, unknown-file retention,
uninstall registration/PATH cleanup and state preservation. Ctrl+C retains the
shared bridge signal-interruption exit code 2; requested shutdown/EOF exit 0.
The only runtime correction was `doctor`: on Windows it now relies on existing
native private-state DACL validation, rather than misleading POSIX mode bits.

A repeat run exposed a fixture publication race: the process-tree test now
atomically renames its complete PID marker before the parent observes readiness.
Hosted CI also reported incomplete network ownership evidence. The fixture's
PowerShell/CIM query was replaced: the probe obtains the same PID/parent/name evidence
directly with Toolhelp32 snapshots, retaining TCP ownership and exact Job Object
membership assertions without depending on CIM startup. Failures retain error types
and worker state, never environment or command-line dumps.

Commands (native `py -3.10 -B`):

- `scripts/build_windows.py`: source manifest, pinned dependencies, 78 payload files,
  portable ZIP, installer and SHA256SUMS; unsigned.
- `scripts/windows_package_acceptance.py --installer dist/jv-cli-0.4.9-windows-x86_64-setup.exe --portable dist/jv-cli-0.4.9-windows-x86_64.zip --node <explicit fixture node.exe>`:
  17 installed tests, zero skips; six socket cases plus installer/console checks.
- `scripts/windows_preflight.py`: 91 shared tests, zero skips.
- `scripts/windows_native_tests.py`: 192 shared/native tests, zero skips (the previous
  185 plus seven portable package-integrity tests).
- `scripts/windows_bridge_acceptance.py --engine <pinned native codex.exe>`:
  192 categorized shared/native tests + 11 public bridge tests + six socket cases,
  all pass with zero skips. Historical restricted investigation remains available.
- `scripts/manage.py verify`: regenerated repository manifest; source changes and
  build/test definitions included, generated artifacts/downloads excluded.

`.github/workflows/windows-package.yml` reproduces the unsigned build, installed
acceptance and source trusted-host gate on Windows Server 2022 without secrets,
then uploads run artifacts. No release/tag publication. Existing Windows job names
now describe their actual gates. Linux Python 3.10 through 3.13 regression/build jobs remain
unchanged; their exact published-SHA results are checked separately, not inferred
from native Windows tests. Source manifest line endings must remain LF before hashing.

Next: JV Desktop Windows integration, separately authorized. Launch installed
`jvcli.exe bridge --stdio --execution-mode trusted-host` from the project cwd with
private pipes and optional absolute isolated JVCLI_HOME. Desktop is untouched.
Restricted-token network-denied Windows execution remains unsupported by Codex
0.149.1 and fail-closed in JV. Trusted-host is for dedicated worker accounts.
No production authentication, real credentials/jobs, external inference, firewall
changes, admin service, engine/version/protocol bump, main merge or tag/release.


## Dedicated Windows trusted-host checkpoint — 2026-10-02

Deployment authority was explicitly changed by the operator: dedicated ordinary
Windows worker accounts intentionally run tools with unrestricted filesystem and
network access and no approval prompts. This is an explicit profile, never a
fallback for failed sandbox enforcement. Starting local/fetched origin:
`f6a83d557fc5e7f3b2e986513eeeb6e7c97bde6a`.

### Public selection and pinned mapping

`jvcli bridge --stdio --execution-mode trusted-host` selects immutable process
policy. `exec` and `resume` accept the same option. No environment alias or new
bridge request field was added. Linux rejects this Windows-only profile and keeps
its existing defaults. Saved trusted-host sessions record `execution_mode` and
require the same explicit selection on resume; legacy metadata remains compatible.

Shared `execution_policy.resolve` maps trusted-host to Codex
`sandbox_mode="danger-full-access"`, `approval_policy="never"`, and enabled tool
networking. The pinned source maps danger-full-access to `PermissionProfile::Disabled`;
no tool sandbox is applied. The existing Windows backend preference remains
unelevated for restricted profiles; it does not override disabled enforcement.
All managed settings are explicit `-c` overrides, outranking project config.
The bypass CLI switch is unnecessary. Engine prompts remain on stdin; no prompt
or credential is added to argv. The engine pin is still 0.149.1, CLI 0.4.9,
bridge protocol 1. No elevated provisioning, WFP, service or firewall changes.

Startup stderr identifies full access, network allowed and approvals never;
stdout remains NDJSON. For explicitly opted-in parents, `session.started.sandbox`
is `danger-full-access`. A trusted-host session requesting read-only or network
denial gets `unsupported_capability`, before engine/session creation. Direct
Windows restricted network-denial configuration raises a clear unsupported error.
The default Windows secure-session guard remains; nothing silently enables this
profile. Historical restricted-token socket failures below are still valid.

### Control-plane changes and evidence

Public Windows sessions now use the existing shared session/bridge core only
when trusted-host is explicit. Native workspace validation rejects reparse/UNC
and unsupported storage through existing Windows primitives before readiness;
this validates control-plane identity, not a tool filesystem containment promise.
Drive roots are rejected correctly. Resume retains workspace/account/origin,
transport, execution-mode and session-lock binding.

Real resume exposed a concrete ACL ownership issue: Codex replaces its own
`engine/config.toml` with inherited ACLs. JV's strict private-file replacement
correctly refused that file. On Windows, JV now owns a separate protected
`engine-config.toml` under the session; complete argv configuration overrides are
authoritative. JV does not relax DACL checks or claim ownership of engine-rewritten
files. Linux's config location/behavior is unchanged.

The new `scripts/windows_trusted_acceptance.py` launches the actual public
`bin/jvcli bridge --stdio --execution-mode trusted-host` in native subprocesses,
with the real pinned engine and a loopback fake JV HTTP service. It injects no
bridge/session implementation bypass. Disposable trusted Python executables are
used so hosted runner ACLs cannot weaken auth-helper executable checks. Tests
keep the operator home path only for workspace validation; tool/engine homes are
isolated and no normal-user credentials/config are read.

Eleven real-engine/public bridge tests cover startup/protocol-only output,
login/logout, two turns, restart/resume/third turn, outside/workspace writes,
approval-never config and unattended completion, tool environment secret
exclusion, password/token absence from output and persisted state, conflicting
owners, corrupt metadata, workspace binding, Thai paths/prompts, malformed input,
final line without newline, EOF, broken output, fatal backpressure, structured
journal reopen, cancellation, shutdown, EOF during a tool, and parent death.
Each tree-ending test observes live child/grandchild handles, waits for termination,
checks an unrelated sentinel survives, and verifies no automatic resubmission.
Remote job state remains unknown on cancellation.

`windows_network_probe.py --execution-mode trusted-host --engine <pinned exe>`
adds six real tool checks: PowerShell/Python/Node, each IPv4 and IPv6. Every local
listener received its connection; TCP owner PID and exact JV Job Object membership
were verified. The original restricted probe and historical evidence are retained.
The combined driver also retains a separately selected restricted investigation;
unsupported network denial is not counted as trusted-host acceptance.

### Gates and next scope

Commands use native `py -3.10 -B`:

- `scripts/windows_preflight.py`: 91 shared tests, zero skips.
- `scripts/windows_native_tests.py`: 185 tests, zero skips: shared 91,
  filesystem/ACL 37, execution/process 18, pipes 16, auth deadlines 7,
  pinned grammar 1, journal durability 11, execution-policy regression 4.
- `scripts/windows_trusted_acceptance.py --engine <pinned exe>`: 11 tests,
  zero skips, including real public sessions and engine tool execution.
- `scripts/windows_bridge_acceptance.py --engine <pinned exe>` is the combined
  authoritative trusted-host gate: those 185 + 11 tests and six network cases,
  all passed with zero skips on this machine.
  It exits nonzero if any required category fails; restricted network-denied
  execution is separately printed as unsupported, not silently skipped.
- Manifest regeneration uses `manage.write_manifest(Path.cwd())`, followed by
  `scripts/manage.py verify`: 124 files verified; no Windows release artifacts
  are built here.

Real native tests are offline/synthetic. Linux full regression remains a CI gate;
Windows execution is not substituted for a Linux run. Packaging/installer,
console UX, Desktop integration, live service acceptance and releases remain
separate milestones. No production authentication, real credentials/jobs,
external inference, version bump, main merge, tag or release occurred.

The sections below retain the earlier secure-sandbox investigation and its
unresolved restriction. They do not describe the explicitly trusted-host authority.

## Valid direct sandbox investigation — 2026-10-01

Started clean at local/fetched origin `bbda38a2e7988fe25a71e455220ab952ab9e3d23`.
Diagnosis only; production code and readiness guards are unchanged.
**Root cause: pinned Codex 0.149.1 restricted-token limitation.** The previous
direct invocation missing required JSON is not evidence and was not used.

Exact pinned source was inspected from `rust-v0.149.1` in ignored downloads:

- [SandboxState schema](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/codex-mcp/src/runtime.rs#L513): camelCase outer fields.
- [PermissionProfile schema](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/protocol/src/models.rs#L407): tagged managed profile, snake_case fields.
- [Direct flag handling](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/cli/src/debug_sandbox.rs#L214): disable-network explicitly replaces profile network with `NetworkSandboxPolicy::Restricted`; cwd comes from state, workspace roots from config at that cwd.
- [Windows backend selection](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/core/src/windows_sandbox.rs#L25): unelevated maps to RestrictedToken; elevated maps to Elevated.

The actual valid JSON used this shape, replacing placeholders with absolute
disposable paths (cwd uses a native file URI; filesystem entries use Windows paths):

```json
{
  "permissionProfile": {
    "type": "managed",
    "file_system": {
      "type": "restricted",
      "entries": [
        {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"},
        {"path": {"type": "path", "path": "<workspace>"}, "access": "write"},
        {"path": {"type": "path", "path": "<private TEMP>"}, "access": "write"},
        {"path": {"type": "path", "path": "<private USERPROFILE>"}, "access": "write"}
      ]
    },
    "network": "enabled"
  },
  "codexLinuxSandboxExe": null,
  "sandboxCwd": "file:///C:/.../private/workspace",
  "useLegacyLandlock": false
}
```

Direct argv through `windows.spawn_engine`, without a shell wrapper:
`[codex.exe, sandbox, -c, windows.sandbox="unelevated", --sandbox-state-json,
json.dumps(state), --sandbox-state-disable-network, --, client.exe, ...]`.
Allow controls omit only the disable-network flag. No extra readable-root flag
is needed because root reads are explicit. Client arguments contain only static
socket diagnostic code and synthetic loopback addresses/ephemeral ports; no
prompt, model call, account or API is involved. Environment/state are disposable.

An automated Python harness owns each listener, launches the engine in the JV
Job Object, queries the accepted socket's TCP owner PID, checks membership of
that exact job, acknowledges the client, collects exit/stdout/stderr, joins the
listener, closes handles, stops the job and removes temporary state. No manual
terminal coordination was needed. Local ignored evidence is retained in
`downloads/direct_network_probe.py` and `downloads/direct_network_results.jsonl`.
Command: `py -3.10 -B downloads/direct_network_probe.py`. This diagnostic records
observations; its successful execution is not an acceptance pass.

| Backend/policy | PowerShell IPv4 / IPv6 | Python IPv4 / IPv6 | Node IPv4 / IPv6 |
| --- | --- | --- | --- |
| Unelevated, disable-network | CONNECTED / CONNECTED | CONNECTED / CONNECTED | CONNECTED / CONNECTED |
| Unelevated, enabled control | CONNECTED / CONNECTED | CONNECTED / CONNECTED | CONNECTED / CONNECTED |
| Elevated, denied or allowed | Not invoked | Not invoked | Not invoked |

All 12 listeners actually received connections; all clients exited 0, printed
`CONNECTED`, had empty stderr and belonged to the JV-owned job. Six actual denial
violations, six working controls, zero skipped unelevated cases. An initial
fixture omitted writable TEMP/USERPROFILE and PowerShell failed in constrained
language in both deny/allow controls; that was not counted as denial. Aligning
private writable roots with JV's configuration produced the matrix above.

**Does JV request the same Restricted policy? Yes.** `_write_engine_config`
sets workspace-write, `sandbox_workspace_write.network_access=false` and
`windows.sandbox="unelevated"`. Pinned
[config conversion](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/config/src/config_toml.rs#L765)
and [built-in profile mapping](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/core/src/config/permissions.rs#L71)
map false to exactly `NetworkSandboxPolicy::Restricted`. The direct Windows
launcher reaches the same legacy spawn preparation and environment-only network
response discussed below. No JV sandbox-state integration fix is justified.

Elevated mode was not invoked: fresh isolated CODEX_HOME has no provisioning
marker/identity. Pinned
[identity.rs](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/windows-sandbox-rs/src/identity.rs#L177)
can automatically request elevated setup when absent/mismatched, and always
refreshes ACLs even when provisioned. We did not inspect private user credentials
or reuse their normal Codex home. The
[setup launcher](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/windows-sandbox-rs/src/setup.rs#L964)
uses ShellExecuteExW with `runas` when elevation is needed. The
[setup helper](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs#L756)
provisions/hides sandbox accounts and a group, changes persistent ACLs, and
configures offline-account firewall/WFP policy. WFP provider/sublayer/filter flags
are persistent. This is not an ordinary-user temporary Job Object setting.
Elevated socket denial remains unproven here; source presence is not acceptance,
especially because WFP errors can be nonfatal to setup.

No UAC, service, account, firewall rule/profile or WFP filter was created/changed.
For intended unprovisioned non-admin usage, `allow_network=False` cannot currently
be guaranteed. Preserve public fail-closed guards; do not silently select elevated
mode or reinterpret loopback as allowed. No production code changed, so unchanged
historical broad gates were not rerun. No production auth/credentials/jobs,
external inference, installer, Desktop, version/pin/protocol, main, tag or release
work occurred. The network acceptance gate remains failing.

This engineering handoff was prepared on Linux on 2026-10-01 and continued on
native Windows the same day. **Native Windows JV CLI is not functional or accepted
yet.** Private NTFS state and kernel locks now have native tests; execution and
packaging remain blocked. Do not distribute this branch as a supported release.

## Network boundary investigation and durable journal — 2026-10-01

Starting local/fetched remote: `abc0d42461069e9ccacc7bb0da1e6b67b6d6c4c6`.
Public Windows ready/session guards remain blocked. This pass changes neither
the engine pin nor permission semantics and does not begin installer/Desktop work.

### Network blocker: identified, not resolved

`scripts/windows_network_probe.py --engine <verified native codex.exe>` exercises
12 actual engine tool cases: PowerShell, Python and Node; IPv4 and IPv6; deny and
allow policy. **All six deny cases connected; all six allow controls connected.**
The script exits 1. It queries `GetExtendedTcpTable` for the accepted connection's
client PID, records only process name/PID/parent PID, and checks `IsProcessInJob`
against the exact JV-owned job handle. PowerShell is the direct child of Codex;
Python and Node are children of that PowerShell tool. Every observed client was
inside the owned job. The connection did not originate from the trusted engine
or an out-of-job broker. No prompt, credentials or whole environment was captured.
The initial PowerShell IPv6 probe required an explicit IPv6 TcpClient constructor;
the corrected allow controls and deny cases both connected, so no failed client
construction is being counted as network denial.

Pinned source evidence (tag `rust-v0.149.1`, not newer documentation):
[spawn_prep.rs](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/windows-sandbox-rs/src/spawn_prep.rs)
calls `apply_no_network_to_env` for legacy/unelevated spawning;
[env.rs](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/windows-sandbox-rs/src/env.rs)
sets proxy/offline variables and deny stubs, including a loopback NO_PROXY list.
These are not an OS socket-denial boundary. The configured sandbox is indeed
`windows.sandbox="unelevated"`; tool descendants inherit the filesystem sandbox
and JV job, but direct sockets bypass those environment conventions.
[wfp.rs](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/windows-sandbox-rs/src/wfp.rs)
documents an already-elevated setup helper and installs persistent user-matched
WFP providers, sublayers and filters. That mechanism was not invoked.

A current-user dynamic WFP session opened successfully, but
`FwpmTransactionBegin0(handle, 0)` returned **5 / access denied**. The session was
closed; no transaction began, no filter/sublayer was added and no policy was
committed. Thus this ordinary-user process cannot install the candidate temporary
WFP boundary. Elevating the pinned helper would entail persistent machine policy
and sandbox accounts, outside this pass's safe boundary.

An outer capability-free AppContainer can deny networking, but applying it to the
whole existing engine also denies the engine's required loopback adapter channel.
Granting broad loopback access would restore the observed tool escape. The current
shared integration owns the engine tree, not the engine's internal per-tool spawn
boundary; no verified tool-only AppContainer hook or private non-network model
transport has been established for this pin. This is an integration blocker, not
a claim that Windows can never implement network isolation. No unproved wrapper,
proxy-only restriction, global firewall change or engine upgrade was substituted.
Crash/cancel/owner-death cleanup of a new network policy is **not accepted**:
no enforcing policy could be installed, so there is none to test or leak.

### Durable structured journal: implemented

`DurableResponseState` persists `structured/state.json`: round request body and
idempotency key before submission, then response identity and published tool
decisions before they may be returned/executed. Success must not acknowledge
only cached data or a rename whose namespace metadata was never flushed. POSIX
already writes/fsyncs a temp file, renames it, then fsyncs the parent directory;
that last operation cannot be copied as `os.O_DIRECTORY` on Windows.

The Windows durable path now creates the private temporary file with native
`FILE_WRITE_THROUGH`, completes its UTF-8 bytes, flushes it, performs the existing
pinned-parent handle-relative atomic rename, then flushes the renamed handle.
The same ACL, owner, reparse, hard-link and fixed-local-NTFS checks apply. Linux's
sequence is unchanged. Microsoft documents NTFS metadata/rename flushing for
[write-through file handles](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
and the native option in [Nt/ZwCreateFile](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/nf-wdm-zwcreatefile).
Hardware that does not honor flush/write-through remains outside a software proof.

Before-rename write/flush/rename failures preserve the prior active record and
clean the owned temporary file. A final flush failure after successful rename is
reported as uncertain durability: the new record is complete but success is not
acknowledged, `write_failed` is set, and callers must stop/reconcile. It is not
rolled back or automatically replayed. A process killed before rename can leave
an orphan temporary file; reopening reads only `state.json`, never that temp.

`py -3.10 -B -m unittest discover -s tests -p test_windows_journal.py -v`:
**11 passed**. Actual handle-mode query proves FILE_WRITE_THROUGH; native file
operations cover UTF-8/Thai, new/replaced/reopened records, injected write/flush/
rename failures, partial temp rejection, sequential and concurrent-reader
replacements, process exit/reopen, and forced writer death before rename.
Sharing contention fails explicitly rather than exposing partial JSON. These
tests prove process/crash behavior and failure reporting, not physical power loss.

The real pinned engine's structured shell-call/continuation now passes using the
native journal. The five original engine isolation checks remain **4 pass / 1
network failure**. The bridge acceptance driver stays nonzero and still requires
full public lifecycle/workspace acceptance in a later milestone.

Final local gates: `py -3.10 -B scripts/windows_preflight.py` passed 91 tests and
compiled 76 Python files; `py -3.10 -B scripts/windows_native_tests.py` passed
181 tests, zero skips (previous 170 + 11 journal tests). Manifest regeneration
used `manage.write_manifest(Path.cwd())`; `py -3.10 -B scripts/manage.py verify`
verified 121 source/documentation files. The loopback network investigation and
real-engine acceptance gates intentionally exit 1; they are not green CI claims.

## Auth deadline checkpoint and sandbox blocker — 2026-10-01

Started from clean local/fetched origin
`c7cdb1d7b50959928467f107d411291a9c3743d5`, whose six CI jobs passed.
Windows bridge auth/logout now use a disposable Job Object-owned Python helper.
Request secrets enter through stdin; the token result uses one explicitly
inherited anonymous result pipe, **not stdout/stderr**, argv, environment or disk.
The helper runs the shared `JvApiClient`; it cannot access the parent's client,
session or bridge objects. Only the calling bridge owner installs a validated
result after child exit and joined I/O, while still within the total deadline.
Timeout kills/waits the job, cancels the result reader, joins communication and
closes handles. Cleanup failure makes the bridge fatal; it cannot replace auth.
Logout drops local token ownership before attempting remote revocation. Late
remote responses cannot install a token or clear a newer client state. Lost
server-side login/revocation results remain uncertain and are not replayed.

The source helper requires a Python executable satisfying the existing executable
ACL policy; tests stage only Python binaries in a disposable trusted directory.
An untrusted development Python installation fails closed. A final packaged
runtime strategy is outside this bridge pass. The helper does not use shell
execution, ambient proxy/config, multiprocessing pickle or asynchronous exception
injection. Linux still uses the existing main-thread signal deadline.

`py -3.10 -B -m unittest discover -s tests -p test_windows_auth.py -v`:
7 passed with real child processes and a loopback HTTP fixture. Covers successful
login/logout, late server responses after timeout, repeated timeout, newer-token
preservation, deterministic bridge recovery, request IDs, queued shutdown during
auth in a subprocess, no surviving workers, released handles, no secrets in child
argv/environment, bridge output or persisted state. This does not yet prove full
public sessions/resume/turn cancellation; the public ready/session guards remain.

The real Windows 0.149.1 engine's apply_patch grammar hash is
`ce2574fac05867f519a0ce3bdae50ce7d68b6d2e5f68d3c0c7e75518142d89b3`.
Its 19 CRLF sequences are the only difference from the certified LF grammar:
normalizing them yields the existing `d6367f48...` hash. Windows accepts only
these two exact hashes, preserving the declaration and grammar; Linux still
accepts only its original hash. `test_windows_grammar.py`: 1 passed, including
altered-grammar rejection. No product/engine/protocol version changes.

Actual engine probes use the shared runner/adapter and scripted local responses.
Four native checks passed: workspace write, outside-workspace write denial,
read-only write denial and absence of JV/adapter/OpenAI secret variables in the
tool environment. **Network denial failed:** with `allow_network=False` and the
configured unelevated sandbox, PowerShell `System.Net.Sockets.TcpClient` connected
to an ephemeral synthetic 127.0.0.1 listener. The listener actually accepted the
connection. Proxy environment settings are therefore not sufficient enforcement.
No external inference/service was contacted. No admin account, firewall rule,
elevated sandbox setup or normal-user engine configuration was changed.

This is a security stop condition: do not enable public sessions or claim offline
bridge acceptance while the pinned sandbox permits forbidden networking. A secure
Windows network-denial design must be proved without weakening the contract;
switching to elevated setup is not a proven fix. Current upstream guidance:
[Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox).
Separately, structured mode reached a POSIX-only `os.O_DIRECTORY` + directory
`fsync` in `DurableResponseState._write`. Its crash/reconciliation durability
guarantee needs a native implementation; it was not removed or silently bypassed.

Authoritative development driver:
`py -3.10 -B scripts/windows_bridge_acceptance.py --engine <verified codex.exe>`.
It runs separate shared/storage/execution/pipe/auth/grammar categories, rejects
skips, runs the five real-engine checks, and exits **1** for the network failure
and incomplete public lifecycle/containment/durable-journal gates. It must not be
treated as green primitive CI. No installer or package work was started.

Final checkpoint commands: `py -3.10 -B scripts/windows_preflight.py` passed
91 tests (74 Python files compiled); `py -3.10 -B scripts/windows_native_tests.py`
passed 170, zero skips: 91 shared + 37 ACL/filesystem + 18 execution + 16 pipe/
dispatch + 7 auth/lifecycle + 1 grammar. `py -3.10 -B scripts/manage.py verify`
verified 119 shipped files. The engine acceptance driver is deliberately red,
with 4/5 real tool-isolation checks passing; full public bridge remains blocked.

## Native pipe continuation — 2026-10-01

Published execution checkpoint `0c6898b300bb3622558a3344ef07962d7f6340fa` normally
and verified the freshly fetched origin matched. The subsequent CI annotation
checkpoint makes failing test names/exceptions available through the public Checks
API; downloading hosted job logs returned HTTP 403 with this session's API access.
All four Linux jobs passed for execution/annotation checkpoints. Hosted native
tests exposed an actual fixture assumption: the runner workspace grants other
principals write access. Disposable `staging-*` fixture roots now receive explicit
trusted inheritable ACLs before public-file/executable tests. Product ACL policy
was not relaxed; the checkout, installed Python and user directories are untouched.

`bridge_io.py` retains one shared framing/serialization/queue implementation.
The lazy `_windows_pipe.py` backend uses synchronous `ReadFile`/`WriteFile` workers
with one outstanding operation each. Input reads are limited to 4096 bytes; the
owner polls without blocking on fragmented input. Windows calls bypass CRT text
translation, preserving UTF-8 and LF output. `CancelSynchronousIo` is repeated
until the worker exits to cover cancellation just before syscall entry; retained
thread handles prevent cancellation from targeting a recycled thread ID. Workers
own pipe buffers only, not bridge/session state. A cancellation failure is fatal.
Output keeps the shared 128 KiB frame limit, 64-frame queue, 250 ms enqueue timeout,
and five-second write deadline. Native pipe-state queries detect idle stdout peer
closure. Files/consoles, overlapped handles and message-mode pipes are rejected;
the tested interface is inherited synchronous byte-stream pipes.

References: [synchronous I/O cancellation](https://learn.microsoft.com/en-us/windows/win32/fileio/canceling-pending-i-o-operations)
and [native pipe connection state](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_pipe_local_information).
Neither reference substitutes for native execution tests.

`py -3.10 -B -m unittest discover -s tests -p test_windows_pipes.py -v`:
16 tests passed on ordinary-user Windows. Coverage includes fragmented bytes,
Thai/Unicode, CRLF, invalid UTF-8 rejection, maximum input, oversize recovery,
large output, EOF/final line, blocked reader/writer, bounded queue backpressure,
write timeout, repeated cancellation races and worker/handle cleanup. A dedicated
subprocess fixture invokes shared bridge dispatch with only workspace checking
injected; it proves protocol-1 startup, shutdown, EOF, malformed input and idle
broken-stdout exit over inherited pipes. Authentication is explicitly forbidden
in this fixture. This is transport evidence, **not public bridge acceptance**.

Checkpoint gates: `py -3.10 -B scripts/windows_preflight.py` passed 91 shared
tests and compiled 68 Python files; `py -3.10 -B scripts/windows_native_tests.py`
passed 162 with zero skips (91 shared, 37 storage, 18 execution, 16 pipe/dispatch).
`py -3.10 -B scripts/manage.py verify` verified 113 source/documentation files.
No Windows ZIP or installed-package test was produced by these gates.

`require_bridge_io` still fails before public ready, and Windows sessions still
fail before auth. Auth/logout deadline isolation, full lifecycle/cancellation,
real-engine tool/sandbox acceptance, workspace/image/download containment,
console, installer/rollback and Windows packaging remain open. In particular,
an arbitrary synchronous auth call cannot safely acquire a deadline by abandoning
a state-mutating Python thread or injecting an asynchronous exception. The next
deadline layer must preserve sole state ownership and prove late-result races.

## Public-file policy continuation — 2026-10-01

### Native execution primitives

The next checkpoint adds `_windows_engine.py` and `_windows_process.py` behind
the existing Windows backend. Discovery validates AMD64 PE32+ executable headers,
the exact pinned `codex-package.json`, and required native helpers. It supports
the npm alias package layout and explicit native paths; `.cmd` shims are rejected.
The package is `@openai/codex@0.149.1-win32-x64`, resolved by the wrapper dependency
alias `@openai/codex-win32-x64`. Its entrypoint is
`vendor/x86_64-pc-windows-msvc/bin/codex.exe`; helpers live in `codex-resources`,
and ripgrep in `codex-path`. No Node shim is needed for the tested version query.
Both upstream archives were downloaded only into ignored repository downloads
and verified against registry SHA-512 integrity before safe member extraction.
Native archive SHA-256:
`513bde2e7a1fe31e9b7ab2c9ec1dc87e54eb93d3adc5ae579452a7f0c09e9ed2`.
Wrapper archive SHA-256:
`1616304fd7883b46d8887cf336496e2ae0cdf9a637b7bdf8824baa98c22c5b7b`.
These are development inputs, not Windows release artifacts or a completed
runtime supply-chain/installation verifier.

Windows environments now derive the system directory through the native API,
use a fixed system PATH, and create isolated HOME/USERPROFILE/APPDATA/LOCALAPPDATA,
TEMP/TMP and CODEX_HOME. Arbitrary parent variables are not copied. The trusted
engine still receives the explicit in-memory local adapter key required by the
shared adapter protocol; tools use `inherit = "none"` and an explicit environment
without that key. Tool CODEX_HOME is separate from engine configuration. Actual
pinned-engine tool environment isolation remains to be proved with scripted tools.
Windows config disables login shells and selects the unelevated sandbox candidate;
no sandbox setup, local-account creation, firewall changes, or tool execution has
been performed by these checks. Current official configuration guidance is at
[Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox) and
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference);
current documentation alone does not establish pinned-engine sandbox acceptance.

Process creation uses `CreateProcessW` with explicit argv quoting, an explicit
environment, inherited stdin/stdout/stderr handles only, and an atomic
`PROC_THREAD_ATTRIBUTE_JOB_LIST` assignment. Each unnamed, non-inherited Job Object
has kill-on-close and no breakaway. A reaper closes the job after engine exit,
terminating orphaned descendants and releasing their pipe handles. Owner death
also closes the job. Unknown process objects cannot be cancelled. Diagnostic
capture is bounded to 128 KiB per stream. Prompt data stays on stdin. Reference:
[process creation attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).

Validation commands, all using `py -3.10 -B`:

| Command suffix | Result |
| --- | --- |
| `-m unittest discover -s tests -p test_windows_execution.py -v` | 18 native execution/discovery/environment tests passed |
| `scripts/windows_preflight.py` | 91 shared tests passed; 64 Python files compiled |
| `scripts/windows_native_tests.py` | 146 passed, zero skips: 91 shared + 37 native storage + 18 native execution |
| `scripts/windows_engine_check.py --engine <verified native bin/codex.exe>` | 2 real pinned-engine checks passed: package/AMD64 validation and owned isolated version query |

Execution tests exercise native jobs, child/grandchild termination, unrelated
sentinel survival, engine-parent exit, owner-process death, denied breakaway,
failed-creation handle counts, timeout cleanup, bounded diagnostic output, Unicode
stdin, and the shared runner's hung-input deadline. Synthetic PE fixtures exercise
package discovery and version/architecture rejection; the separate engine check
uses the actual downloaded executable. Development Python's original directory
failed the executable ACL policy, so tests copy only Python binaries into a
disposable repository directory rather than relaxing the ACL check.

Public Windows sessions now explicitly fail before authentication while sandbox
and workspace acceptance is unfinished. Bridge ready remains blocked. Remaining
gates: real-engine scripted tool isolation and filesystem/network sandbox tests;
Windows bridge pipes and auth/logout deadlines; workspace/image/download safety;
console/Thai IME; per-user installation, rollback, launcher and Windows artifacts.
No Windows bridge or installed-package acceptance is claimed. Linux behavior and
pins remain unchanged; shared-code Windows branches are conditional on `os.name`.

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
