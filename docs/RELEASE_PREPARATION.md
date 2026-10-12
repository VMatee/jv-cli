# JV CLI 0.5.3 source preparation — 2026-10-13

Official publication is pending. Stable Latest remains 0.5.2. Keep `v0.5.3`
unpublished until final Windows acceptance and exact-main regression/package
Actions workflows are green. No production service or installed app was changed.

## Integrated history

- Prior main: `9a8aa1060d79657db48a84d5d93efb27c05f66d8`.
- Linux vision: `3a1bfab0868ecb8b91cd8aa80bd9fbdf1b458e61`.
- Immutable Windows RC1: `fdf3328ddc83fa07b6f461362bbe17f3785435f8`,
  tag `windows-rc-0.5.3-1`, already containing the Linux commit.
- Certified Windows grammar fix: `ffe028d76bf20ba893e54fb0295cfd45bcb54936`.
- Historical Windows investigation through
  `b897746a0a2c20e0c7b05a0ed889bdd650a6f9cc` is retained unchanged.

Original branches and tags remain. Historical PowerShell feasibility and the
one-off 0.4.4 recovery workflow are alternatives, not further product updates.
Useful safety guidance from the preserved Linux documentation branch is included.
VERSION remains 0.5.3, engine 0.149.1, protocol 1. The grammar fix accepts only
exact certified declarations and emits LF without changing patches or engine
history. Linux permissions and Windows explicit trusted-host policy are preserved.

## Offline Linux validation

`./test.sh`: 534 tests ran, 442 passed and 92 native Windows tests skipped.
Normal/offline packages, checksums, extracted verification, isolated-home offline
installation/doctor, pinned-engine execution, agent and completion checks passed.
The engine checks exercised workspace/read-only/network restrictions.

Synthetic vision passed PNG/JPEG/WebP, two turns, further edits, restart/resume,
unsupported-service single submission, a surviving bridge and explicit Legacy
selection. Desktop's real Rust supervisor passed the same fixture with bounded
events containing neither image payloads nor credentials. These are loopback
fixtures, not live provider or native Windows acceptance. Exact published SHAs,
final package verification and CI status are in the platform's 2026-10-13 checkpoint.

## Windows handoff

Use the exact published main SHA in that checkpoint and a clean checkout. Native
AMD64 Windows 10/11, Python 3.10+ for drivers, Node, Playwright Chromium and Pillow
are required for the offline vision gates. Package CI uses Python 3.10 and Node
22.12.0. The builder verifies embedded Python 3.10.11, engine 0.149.1 and Inno Setup
6.4.3. Keep existing pins and ordinary-user dedicated-worker boundaries.

Run `scripts/windows_preflight.py`, `scripts/windows_native_tests.py`,
`scripts/windows_bridge_acceptance.py --engine ABSOLUTE_CODEX_EXE`, then
`python -B scripts/build_windows.py` and
`scripts/windows_package_acceptance.py --installer DIST_SETUP_EXE --portable DIST_ZIP --node ABSOLUTE_NODE_EXE`.
Cover DACL state, process/pipe ownership, cancellation, deadlines, resume, grammar,
image history, trusted-host networking, rollback/reinstall, uninstall and PATH/state
retention. Use synthetic accounts and disposable homes only.

Run `scripts/windows_vision_acceptance.py` with absolute `--engine`, `--node`,
`--playwright`, `--browsers` paths, against source and with `--launcher` pointing
to the accepted installed/extracted executable. Repeat with `--desktop-probe`
pointing to the matching Desktop `vision_fixture.exe`.

Expected Windows assets: `jv-cli-0.5.3-windows-x86_64.zip` and
`jv-cli-0.5.3-windows-x86_64-setup.exe`.

Collect actual accepted packages with `scripts/release_assets.py collect --source
dist --output EMPTY_DIRECTORY --platform windows --version 0.5.3 --commit
EXACT_MAIN_SHA`. Verify with `scripts/release_assets.py verify --output DIRECTORY
--platform windows --version 0.5.3 --commit EXACT_MAIN_SHA`. Verify SHA256SUMS,
BUILD-INFO.json and embedded BUILD.json source commit/manifest. Never reuse RC
metadata for final-main builds. Assembly requires matching Linux/Windows commits.

After Windows acceptance and both green exact-main workflows, the separately
authorized release phase may create new `v0.5.3` at that same main SHA and push
the tag normally. Let the existing tag-only workflow verify, assemble and publish
once; verify two fresh public downloads. Never replace RC1 or existing tags/assets.
[Release notes](releases/0.5.3.md) describe prepared user-facing behavior.

[The historical Windows investigation](WINDOWS_INPUT_001_HANDOFF.md) records failed
live account admission against an older server revision. Later platform source has
administrator-managed Structured permissions/shared workers. Offline parity does
not prove current eligibility of that Windows account. Renewed real acceptance
needs separate authorization and a fresh disposable session; never replay the
consumed failure or silently change account, transport or routing.
