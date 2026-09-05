# JV CLI

JV CLI is an AI coding-agent CLI that connects to JV LLM while running development tools locally in the user's workspace.

Command: `jvcli`

This repository is preparing its first public release. The engine compatibility target is pinned to `@openai/codex@0.149.1`.

## What is JV CLI?

JV CLI provides an interactive and one-shot coding workflow backed by the JV job API. A small authenticated loopback adapter translates between the pinned agent engine's Responses protocol and JV jobs. Shell commands and patches run locally under the engine sandbox; the API/model receives the task and context needed to produce responses.

JV CLI is an independent project and is not endorsed by OpenAI. Required upstream notices are retained in this repository and in release archives.

## Quick Start

```bash
git clone https://github.com/VMatee/jv-cli.git
cd jv-cli
./install.sh
export PATH="$HOME/.local/bin:$PATH"  # only if the installer says it is needed
jvcli doctor
jvcli login
```

The default install is user-owned and does not require `sudo`. It installs the application under `$HOME/.local/share/jv-cli`, keeps the pinned engine under that directory's `runtime/`, and creates `$HOME/.local/bin/jvcli`.

## Requirements

- Linux on x86_64/amd64
- Python 3.10 or newer
- Node.js 18 or newer and npm
- `curl` and `unzip`
- Network access to npm during initial engine setup and to the configured JV API during use

On Ubuntu, install missing prerequisites explicitly:

```bash
sudo apt update
sudo apt install python3 nodejs npm curl unzip
```

JV CLI reports missing prerequisites but never runs `apt` or `sudo` itself. Do not run `./install.sh` with `sudo`.

## Install from Git

```bash
git clone https://github.com/VMatee/jv-cli.git
cd jv-cli
./verify.sh
./install.sh
```

If `$HOME/.local/bin` is absent from `PATH`, the installer prints a command to add it for the current shell. It never edits startup files by default. To request one idempotent `~/.bashrc` entry:

```bash
./install.sh --add-path
```

Use `./install.sh --no-engine` only for packaging/tests; coding commands require the pinned engine. `--offline` tells npm to use its isolated cache and does not make inference offline.

## Install from GitHub Release

After a GitHub Release exists, the repository includes a checksum-first bootstrap installer:

```bash
curl -fsSL https://raw.githubusercontent.com/VMatee/jv-cli/main/scripts/install-from-github.sh | bash
```

No public release exists at the time of this initial repository publication, so the command above is documented for the future release and is not yet claimed to succeed. The script accepts HTTPS only, downloads the ZIP and SHA-256 from `VMatee/jv-cli`, verifies before extraction, and uses no `sudo` or `eval`.

## Login

```bash
jvcli login
jvcli auth status
```

The password prompt is hidden. JV CLI saves only the username and API origin in its private state directory; it does not intentionally persist the password or bearer token. No `--password` option exists. Each process authenticates as needed and keeps its bearer token in memory, with best-effort logout/revocation.

## Basic Usage

```bash
cd ~/some-project
jvcli
jvcli exec "inspect this project"
jvcli exec --read-only "inspect this project"
jvcli sessions
jvcli resume SESSION_ID
```

The working directory selected when `jvcli` starts is the workspace. Normal write mode may intentionally modify that project.

## Interactive Mode

Run `jvcli` from a dedicated project directory. Interactive commands include `/help`, `/status`, `/new`, and `/exit`. Saved sessions use separate engine homes and locks. Resume requires the same workspace, username, and API origin.

## One-shot Exec

```bash
jvcli exec "run the tests and explain any failure"
jvcli exec "update the README, then show the diff"
```

The prompt is sent to the engine over standard input rather than exposed as a child-process argument.

## Read-only Mode

```bash
jvcli exec --read-only "review this repository without changing files"
```

Read-only mode requests an engine-enforced read-only sandbox. Tool network access is denied by default. For a trusted write-mode task that explicitly needs dependency downloads, use `--allow-network`; it cannot be combined with `--read-only`.

## Project Isolation

Application source, runtime, cache, engine configuration, and sessions remain under `$HOME/.local/share/jv-cli`. JV CLI uses a separate `CODEX_HOME` for each saved run and does not read, write, or replace your personal `~/.codex` configuration or globally installed engine.

Only the selected workspace receives normal workspace-write permission. Tests cover writes outside the workspace, read-only writes, and tool-network denial. This isolation is not a VM: the chosen project can be changed in write mode, and no claim is made that every user-readable file is unreadable. Use a dedicated OS account, container, or VM for stronger isolation.

## Portable Mode

```bash
git clone https://github.com/VMatee/jv-cli.git
cd jv-cli
./install.sh --portable
source ./activate.sh
jvcli doctor
```

Portable mode keeps source, runtime, state, cache, and backups inside the extracted repository. It creates nothing under `~/.local/share/jv-cli` or `~/.local/bin`. `activate.sh` changes `PATH` only for the current Bash session and is unnecessary for a normal installation.

## Configuration

The private file `$HOME/.local/share/jv-cli/.state/config.json` may contain only:

```json
{
  "base_url": "https://ai.openjvspace.com",
  "username": "your-user"
}
```

`JV_API_BASE_URL` and `JV_API_USERNAME` can override these values. `JV_API_PASSWORD` exists for carefully controlled noninteractive use; JV CLI removes it from its own environment before launching the agent engine. Never commit credentials or put passwords in shell history.

## Updating

Release-based `jvcli update` is not exposed in this version. Safe update needs an idle installation, verified archive, state/runtime preservation, backup, and rollback. The retained manual path provides those source replacement protections:

```bash
unzip jv-cli-NEW_VERSION-linux-x86_64.zip -d /tmp/jv-cli-update
cd /tmp/jv-cli-update/jv-cli
./verify.sh
./upgrade.sh "$HOME/.local/share/jv-cli"
"$HOME/.local/share/jv-cli/install.sh"
```

Close all JV CLI sessions first. The upgrade preserves `.state/`, `runtime/`, and `.cache/`, and backs up replaced source under `.backups/`.

## Uninstall

```bash
jvcli uninstall
# or:
"$HOME/.local/share/jv-cli/uninstall.sh"
```

Both commands warn before removing `$HOME/.local/bin/jvcli` and `$HOME/.local/share/jv-cli`. They never delete user projects. For noninteractive automation after reviewing the warning, add `--yes`. To remove program/runtime/cache while retaining local account and session state:

```bash
jvcli uninstall --keep-state
```

Portable installations are removed by moving or deleting their extracted folder after all sessions exit; the normal uninstall command deliberately targets only the fixed per-user install paths.

## Security

- Password input is hidden; plaintext passwords and bearer tokens are not intentionally stored.
- JV credentials are excluded from the child engine environment.
- The loopback adapter uses a random per-session key and validates local requests.
- Downloads are bounded and validated; source upgrades verify the package manifest.
- The model/API receives prompts, relevant conversation/tool results, and data necessary for requested tasks.
- Selected projects may intentionally be modified in write mode.
- Python and operating-system process memory cannot guarantee secret zeroization.

See [docs/SECURITY.md](docs/SECURITY.md) for boundaries and limitations.

## Troubleshooting

Run:

```bash
jvcli doctor
jvcli auth status
```

If `jvcli` is not found, add `$HOME/.local/bin` to the current shell's `PATH`. If the engine is absent or mismatched, rerun `./install.sh` from a trusted clone or the installed `install.sh`. Do not install an unrelated similarly named system package. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

If a completed model job returns malformed tool JSON or a known generic error answer, JV CLI requests up to two corrected responses before stopping with the job ID. No rejected tool call executes. Corrections can consume additional quota and cannot guarantee model quality; `--allow-network` only changes tool networking, not response formatting.

The model's server environment is separate from your PC. Your workspace does not need to be mounted on that server. The bridge explicitly delegates tools to the client and requests protected JSON code blocks. If an older session claims your existing project is unavailable, update and start a fresh session; do not change paths or weaken sandboxing.

## Development

Use portable mode or run `./jvcli` directly from the repository. Generated state, runtime, caches, backups, build output, local environment files, and Python bytecode are ignored.

## Running Tests

```bash
./test.sh
./verify.sh
python3 -B scripts/engine_smoke.py
```

The unit suite uses temporary homes and mock services. The engine smoke test uses the real pinned local engine with a scripted loopback model and does not contact the live JV API. `scripts/live_smoke.py` is optional, requires an account, asks for confirmation, and may consume quota.

To additionally check generated Flask files and HTML/CSS responses after a malformed reply, pass `--flask-python /absolute/path/to/venv/bin/python` to `engine_smoke.py`, using a disposable virtual environment that already contains Flask. The check uses Flask's test client, installs no packages itself, and leaves no server running. It tests adapter/tool integration, not the live model's coding ability.

Build and independently verify a release:

```bash
./scripts/build-release.sh
cd dist
sha256sum -c "jv-cli-$(cat ../VERSION)-linux-x86_64.zip.sha256"
```

## Architecture

```text
jvcli CLI
  -> authenticated loopback Responses adapter
    -> JV HTTPS job API
  -> pinned local Codex engine
    -> sandboxed shell_command / apply_patch in the selected workspace
```

The Python modules separate CLI/session management, protocol conversion, transport, adapter handling, and filesystem safety. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Upstream Attribution

JV CLI retains `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and the upstream Codex license/notice under `third_party/openai-codex/`. The engine is installed locally from the pinned `@openai/codex` npm package and is not included in this repository or release archive. See [docs/UPSTREAM.md](docs/UPSTREAM.md).
