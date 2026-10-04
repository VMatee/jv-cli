# JV CLI

An AI coding assistant for your terminal. Ask questions about a project, make changes, run checks, and return to saved work.

**Source version: 0.5.1** · [Published releases](https://github.com/VMatee/jv-cli/releases/latest) · [What's new](docs/CHANGELOG.md)

## Get started

### Windows dedicated workers

Download the Windows AMD64 installer or portable ZIP from
[JV CLI Releases](https://github.com/VMatee/jv-cli/releases/latest). See
[Windows installation](docs/WINDOWS_INSTALL.md). Windows workers must explicitly
select `--execution-mode trusted-host`. The instructions below describe the Linux
release.

### Linux requirements

- Ubuntu/Linux x86_64 for the Linux packages below.
- Python 3.10+ and an existing JV account.
- For the normal ZIP: Node.js 18+, npm, and internet access during installation.
- For the offline ZIP: `unzip` and `sha256sum`; Node.js is included and npm is not required.
- A connection to the JV service is still required to sign in and run AI tasks.

### Install

Download and run the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/VMatee/jv-cli/main/scripts/install-from-github.sh -o install-jvcli.sh
bash install-jvcli.sh
export PATH="$HOME/.local/bin:$PATH"
jvcli --version
jvcli doctor
```

The installer downloads the latest release and verifies its checksum. Installation is per-user and does not require `sudo`. Review downloaded scripts before running them.

Prefer a manual download? Get the ZIP and matching `.sha256` file from [Releases](https://github.com/VMatee/jv-cli/releases/latest), then:

```bash
sha256sum -c jv-cli-0.5.1-linux-x86_64.zip.sha256
unzip jv-cli-0.5.1-linux-x86_64.zip
cd jv-cli
./verify.sh
./install.sh
```

Stop if verification fails. The application is installed under `~/.local/share/jv-cli` with a command at `~/.local/bin/jvcli`. Shell startup files change only if you explicitly use `./install.sh --add-path`.

### Install without downloading dependencies

Download `jv-cli-0.5.1-linux-x86_64-offline.zip` and its matching `.sha256` file from [Releases](https://github.com/VMatee/jv-cli/releases/latest). Copy both files to the Linux computer, then run:

```bash
sha256sum -c jv-cli-0.5.1-linux-x86_64-offline.zip.sha256
unzip jv-cli-0.5.1-linux-x86_64-offline.zip
cd jv-cli
./verify.sh
./install-offline.sh
export PATH="$HOME/.local/bin:$PATH"
jvcli --version
jvcli doctor
```

This ZIP contains the JV CLI source, the pinned agent engine, and Node.js for Ubuntu/Linux x86_64. Installation uses the bundled files without npm or an internet connection. The computer still needs Python 3.10+, standard Linux libraries, and internet access to the JV service when using AI features. No system packages are installed or changed.

### Sign in

```bash
jvcli login
```

Use your existing JV account. Password entry is hidden. JV CLI remembers your username and service address; it asks for your password again when authentication is needed.

### Start working

```bash
cd ~/my-project
jvcli
```

Or give it a single task:

```bash
jvcli exec "Explain this project and suggest improvements"
jvcli exec "Add tests for the calculator and run them"
```

The directory where you start is your workspace. Normal sessions can modify its files. Review changes and test results before relying on them.

## Everyday commands

| Task | Command |
| --- | --- |
| Interactive session | `jvcli` |
| One task | `jvcli exec "Your task"` |
| Inspect without editing | `jvcli exec --read-only "Review this project"` |
| List saved sessions | `jvcli sessions` |
| Continue saved work | `jvcli resume SESSION_ID` |
| Ask a direct question | `jvcli ask "Explain this error message"` |
| Ask about a file | `jvcli ask --file screenshot.png "Explain this screenshot"` |
| Check your setup | `jvcli doctor` |
| Show version/help | `jvcli --version` / `jvcli --help` |

In an interactive session, type `/` to see commands with Thai descriptions. Continue typing to narrow the list, press Tab to complete a suggestion, or use arrow keys and Enter to select one. Misspelled commands suggest a likely spelling and never submit a task. Slash commands stay in English: `/help`, `/status`, `/permissions` (or `/permission`), `/new`, `/exit` (or `/quit`), and `/logout`. `/exit` keeps the saved account; `/logout` forgets it. Thai task input is supported, and JV CLI asks the assistant to answer in the task's language when practical. Resume from the same workspace with the same account and service address.

Use `--verbose` for more detail. `jvcli exec --json "Your task"` provides JSONL output for automation.

## Linux workspace permissions

| Mode | Workspace edits | Network access by project tools |
| --- | --- | --- |
| Default | Allowed | Enabled |
| `--no-network` | Allowed | Disabled |
| `--read-only` | Denied | Disabled |

These flags work with interactive sessions, `exec`, and `resume`. `--allow-network` explicitly selects the default network-enabled write mode and cannot be combined with `--read-only`. The service connection still needs internet access when project-tool networking is disabled.

Permissions do not grant administrator privileges. Network-enabled tools may send data to external services. Use a dedicated project directory and keep secrets out of files you ask JV CLI to inspect. See [Security and privacy](docs/SECURITY.md).

## Optional image-assisted tasks

For accounts with the required service capability, enable image-assisted coding explicitly:

```bash
JVCLI_AGENT_API=1 jvcli exec --image screenshot.png "Improve the layout shown in this screenshot"
```

Use up to four PNG, JPEG, or WebP images located inside your workspace. Symlinked image paths are rejected. Use the same mode when resuming the session. Availability depends on your account; ask your service administrator if a capability is unavailable.

## Linux update or uninstall

Close all JV CLI sessions, then download the new ZIP and checksum from [Releases](https://github.com/VMatee/jv-cli/releases/latest). Extract it into a new directory, verify it, and run:

```bash
./verify.sh
./upgrade.sh "$HOME/.local/share/jv-cli"
"$HOME/.local/share/jv-cli/install.sh"
jvcli --version
```

The updater preserves settings and saved sessions and backs up replaced application files. Do not overwrite a modified source checkout or force an update through a conflict.

To uninstall, review the confirmation shown by:

```bash
jvcli uninstall
```

Use `jvcli uninstall --keep-state` to retain account settings and saved sessions. User project directories are not removed.

## More help

- [Configuration](docs/CONFIGURATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Security and privacy](docs/SECURITY.md)
- [Installation checks](docs/ACCEPTANCE.md)
- [Changelog](docs/CHANGELOG.md)

## License

See [LICENSE](LICENSE), [NOTICE](NOTICE), and [third-party notices](THIRD_PARTY_NOTICES.md).

## Desktop and machine integration

JV CLI provides `jvcli bridge --stdio`, a versioned machine NDJSON interface
for Linux and explicitly selected Windows trusted-host workers. Existing terminal commands remain compatible. Bridge authentication
is memory-only and does not persist passwords. Image requests through the bridge
are deferred; terminal image support is unchanged. Integration developers should
read [the protocol contract](docs/BRIDGE_PROTOCOL.md).
