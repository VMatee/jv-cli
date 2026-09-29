# Phase 3: compatibility inventory and engine feasibility

## Result

The pinned engine's package metadata names a Windows x64 native binary. The npm
registry currently serves the matching `0.149.1-win32-x64` package, restricted to
`win32`/`x64`. That is a distribution check, not evidence that JV CLI runs on
Windows. The package reports approximately 391 MB unpacked; it was not downloaded
on this Linux host.

An isolated mock probe in `scripts/windows_engine_probe.py` ran against the
installed **Linux** native engine version 0.149.1. All six cases now pass with
twelve synthetic model requests and six local shell executions:

1. Read a real workspace file; return actual tool output to a second mock model
   request; capture the final answer.
2. Write a disposable file inside the workspace in workspace-write mode.
3. Attempt to write a file outside the workspace; original contents remained.
4. Attempt to write inside the workspace in read-only mode; file stayed absent.
5. Prove a loopback target is reachable outside the sandbox, then attempt to reach
   it from the sandboxed tool with network disabled; no request reached the target.

The sixth case initially **failed**: the synthetic shell tool received the
nonempty ephemeral `JVCLI_ADAPTER_KEY` value despite the configured `exclude`
list. Its value was never printed or persisted. The Windows worktree now also
sets the tool copy of that variable to an empty value; the pinned Linux engine
continues authenticating to the loopback adapter and the tool gets no key value.
The current probe treats an absent or empty tool variable as safe, and a
nonempty one as failure. Native Windows behavior remains unverified.

The probe uses the current adapter with a synthetic client, a fresh temp directory,
an isolated environment, and the same pinned config/CLI switches as `cli.py`. It
does not authenticate or send a real inference. No credential value, prompt, runtime
key value, tool output, or child environment is printed. The source code still has
Linux-only imports, so native JV CLI startup remains blocked on Windows.

### Adapter key isolation finding

`cli._write_engine_config()` explicitly sets `shell_environment_policy.exclude`
to include `JVCLI_ADAPTER_KEY` and sets `ignore_default_excludes=false`. The probe
mirrors that configuration. A controlled run using the **actual**
`cli._write_engine_config()` and `cli._engine_env()` in a temporary directory
confirmed the same key-presence result. This checks the Linux baseline source
without changing it or sending an inference. The installed Linux copies of
`cli.py`, `adapter.py`, and `protocol.py` hashed identically to both source
worktrees before the safeguard was added. The original Linux checkout and
installation retain that baseline; only this Windows branch has the safeguard.
This strengthens the applicability of the original mock finding to installed
0.4.7 code.

Additional isolated variations found that `inherit=none`, an explicit `exclude`
for a separate synthetic sentinel, and a legacy `include_only` list did not remove
their inherited variables from this tool path. An explicit `set` value did reach
the tool. An empty `set.JVCLI_ADAPTER_KEY` now passes the identical mock test
and a separate round using the actual JV CLI config generator and child
environment. The exact reason the `exclude` rule is ineffective in pinned
engine 0.149.1 remains **unknown**. [Official OpenAI Docs describe the
intended shell environment policy and filter order](https://learn.chatgpt.com/docs/config-file/config-advanced#shell-environment-policy);
the observed behavior here is from the pinned local binary.

The current Linux CLI uses the same engine/configuration path, so this finding
also warrants a separate security review of the Linux installation. It does not
show that any real job read the key. No production or original Linux files were
changed during the probe.

**Native Windows feasibility and security gate: PENDING.** The Linux key
isolation case passes after the safeguard, but this host is Linux x64; `pwsh`,
Wine, and a Windows VM are absent. Do not describe Windows support as working
until the native Windows probe and remaining port gates pass.

## Concrete compatibility inventory

| Boundary | Exact current assumption | Windows work and acceptance |
| --- | --- | --- |
| CLI import | `lib/jvcli/cli.py` imports `fcntl` unconditionally; it imports `slash_ui.py`, which imports `termios` and `tty` unconditionally. | Split POSIX/Windows implementations before importing the full CLI on Windows. Preserve Linux imports and behavior. |
| Engine selection | `cli._find_engine()` recognizes executable `runtime/node_modules/.bin/codex` or `runtime/bin/codex`; installer verifies the same POSIX launcher. | Locate pinned native `codex.exe` or a reviewed `node` plus JS argv. Avoid batch-file quoting ambiguity. Verify version and CLI contract. |
| Engine child | `cli._run_engine()` passes the prompt on stdin, starts a POSIX session, and `cli._stop_process()` signals the POSIX process group. | Keep stdin and explicit argv. Provide owned Windows process-tree cancellation. Test Ctrl+C and timeout with descendants; never replay an uncertain request. |
| Child environment | `cli._minimal_env()` keeps POSIX variables; `cli._engine_env()` sets HOME/TMPDIR/XDG/CODEX_HOME. | Allow only necessary Windows system variables and private per-run paths. Ensure the tool child never inherits adapter keys or JV credentials. |
| Session/update locks | `cli._run_session()` and `scripts/manage.py` use `fcntl.flock` and `O_NOFOLLOW`. | Implement shared installation and exclusive session locks with cross-process tests. Fail closed on ambiguous ownership. |
| Terminal | `slash_ui.py` uses POSIX raw TTY, `select` on an integer fd, and readline; terminal tests use `pty`. | Provide a native console editor or safe fallback. Verify slash suggestions, Thai IME, paste, Ctrl+C, redirection, and hidden password input. |
| Private state | `safety.py` uses POSIX chmod/fchmod, `O_NOFOLLOW`, and symlink checks. | Specify and test per-user ACLs, reparse/junction handling, private atomic writes, and safe replacement. No broad permission fallback. |
| Upload and images | `transport.py` and `images.py` use `O_DIRECTORY`, `O_NOFOLLOW`, `dir_fd`, and no-overwrite hard links. | Use Windows-safe, race-resistant file handles; validate drive paths, case folding, reserved names, UNC policy, and Unicode filenames. |
| Structured state | `structured.py` opens a directory FD; `agent.py` and protocol code share the adapter and safety module. | Replace only platform-dependent state operations, then test legacy and Wire call/result identities. |
| Installation | `scripts/manage.py` rejects non-Linux, assumes `.local/share`, a symlink launcher, `.bashrc`, and `os.geteuid()`. Shell entry points are POSIX. | Build a separate per-user Windows installer and private preview state. Keep the existing Linux installer unchanged. |
| Distribution | `scripts/build_release.py` names Linux ZIPs and POSIX permission bits. The linked worktree `.git` file exclusion is now fixed and tested in this branch. | Distinct Windows artifact, manifest/checksum, no Git pointers or private paths. Preserve the `.git` file exclusion regression. |
| CI | `test.yml` runs Ubuntu only; `release.yml` publishes on `v*.*.*` tags. Some tests import `pty` or assume Bash and chmod. | Add Windows offline matrix/probe and platform-specific tests without changing Linux gates or invoking the tag release workflow. |

The adapter, model protocol, and synthetic client import on Linux without `cli.py`.
This permits the standalone feasibility probe to exercise the pinned engine before
the Windows CLI port exists. It does not establish that the full CLI imports on
Windows; that is the first Phase 4 implementation gate.

## Native Windows probe recipe for a future agent

Run this in an ordinary, disposable Windows 11 x64 user session with PowerShell 7,
Python 3.10+, Node/npm, and enough temporary disk space for the pinned engine. Do
not use an administrator shell to claim ordinary-user sandbox support. Use a
checkout of `feature/windows-powershell` and no real JV account.

```powershell
$probeRoot = Join-Path $env:TEMP ('jvcli-engine-probe-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $probeRoot | Out-Null
npm install --prefix $probeRoot --ignore-scripts --no-audit --no-fund '@openai/codex@0.149.1'
$engine = Join-Path $probeRoot 'node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe'
if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) { throw 'Pinned native engine is absent' }
python -B scripts/windows_engine_probe.py --engine $engine
```

The probe's output must say `result=PASS`, `cases=6`,
`synthetic_model_requests=12`, `shell_executions=6`, all three denial fields and
`adapter_key_value_hidden_from_tool` true, and `real_inference_submitted=false`. Its
exit code must be zero. The current Linux result is `PASS`; this does not predict
the Windows result. Never set a bypass sandbox mode or weaken the key
isolation check to make the probe pass. Keep probe artifacts private and remove
the disposable package after recording the result; preserve failed-run evidence
until diagnosis is complete.

If GitHub hosted Windows CI is used later, scope its job to this branch with
read-only repository permissions, no secrets, and no release/tag trigger. A hosted
runner still does not replace the ordinary-user terminal and ACL acceptance run.

## Next engineering order

1. The adapter-key safeguard has a pinned Linux engine mock proof. Keep keys out
   of tool output and do not change the original Linux checkout as part of this
   Windows worktree.
2. Run the native probe and record exact Windows version, Python/Node/PowerShell
   versions, engine SHA/version, pass/fail classifications, and sandbox behavior.
3. The root `.git` pointer packaging inventory has a focused regression test.
4. Build narrow platform interfaces for locks, terminal, process tree, environment,
   and private files. Preserve the current Linux behavior.
5. Extend the probe or full test suite for Windows legacy and Wire tool/continuation
   flow, then continue Phases 4–8 of `WINDOWS_DEVELOPMENT.md`.

The native probe is still pending here; this phase is partially complete. No
production or customer acceptance was attempted.
