# Windows installation

JV CLI supports dedicated Windows 10/11 AMD64 worker PCs using an ordinary
Windows account. The Windows installer is unsigned; Windows may show SmartScreen or publisher
warnings. SHA-256 verifies the downloaded bytes, not publisher identity. Keep Windows Firewall
enabled. No Administrator account, service or separate Python, Node or Codex
installation is needed.

## Install

Verify the downloaded artifact against `SHA256SUMS` from the same release with
`Get-FileHash -Algorithm SHA256`, then run
`jv-cli-0.5.2-windows-x86_64-setup.exe`. The default per-user application directory
is `%LOCALAPPDATA%\Programs\JV CLI`. The PATH option adds that directory to your
user PATH; open a new terminal afterward. Unattended installation accepts
`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.

The portable ZIP contains the same runtime. Extract it into a dedicated local
directory and invoke `jvcli.exe` by absolute path; portable extraction does not
change PATH or register an uninstaller. Network shares and reparse-point
application/state paths are unsupported.

```powershell
jvcli --version
jvcli doctor
jvcli bridge --stdio --execution-mode trusted-host
```

Trusted-host explicitly permits tools to access files outside the workspace and
use the network, with no approval prompts or Codex tool sandbox. Tools have the
ordinary privileges of the account running JV CLI. Use a dedicated worker account.
Process ownership, credential isolation, bridge framing and journal durability
remain enabled. Bridge stdout contains protocol events; diagnostics use stderr.
Windows restricted-token network-denied execution remains unsupported. Requests
requiring enforceable network denial fail closed; trusted-host does not fix that
limitation.

## State, upgrades and uninstall

Mutable state is separate: `%LOCALAPPDATA%\JV\jv-cli`. An absolute `JVCLI_HOME`
overrides that location, including for an isolated Desktop integration. Do not
put state inside the application directory. The bundle includes Codex 0.149.1;
it does not discover or download a newer engine through PATH.

Shut down JV CLI processes before running setup again to reinstall/upgrade.
Setup refuses active application use. Existing state and session schemas are
preserved. Uninstall through Windows installed apps or `unins000.exe` in the
application directory. Uninstall removes application files and the PATH entry
it added, and **preserves user state**. It does not delete unknown files placed in
the application directory. There is no implicit remove-data option.

## Clean-machine check

On a disposable AMD64 Windows account without development tools, verify the ZIP
and installer hashes, install, open a new PowerShell 5.1 terminal, and run the
commands above. Send `{"type":"bridge.shutdown","request_id":"check"}` on stdin
and confirm clean exit. Use synthetic accounts and loopback fixtures for full
acceptance. Repeat setup, then uninstall, confirming a disposable `JVCLI_HOME`
is preserved. No real credentials or production jobs are required.

Install JV Desktop separately; it uses its own private CLI state and launches
`jvcli.exe bridge --stdio --execution-mode trusted-host`.
