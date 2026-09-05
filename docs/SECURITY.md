# Security boundaries

## What this build does and does not isolate

The normal installer uses `~/.local/share/jv-cli` for application, local npm engine, state, cache, and backups, plus a launcher symlink at `~/.local/bin/jvcli`. Portable mode keeps all of those in the extracted repository. It does not use sudo, global npm installation, system directories, or profile edits unless `--add-path` is explicitly requested. This is installation isolation, **not** a virtual machine, filesystem container, or guarantee that other projects cannot be affected by arbitrary programs.

For coding tools the launcher requests the pinned engine's `workspace-write` sandbox by default, with networking disabled, approval policy `never`, and no bypass switch. The selected workspace is writable, plus the session's private tool HOME and temporary directory. `--read-only` requests read-only access. Read access to other user-accessible paths is not represented as blocked. Runtime sandbox enforcement depends on the engine/kernel; the real-engine acceptance test must pass on each deployment class.

The launcher refuses obvious unsafe workspace roots (filesystem root, your home, the installation itself or its ancestors) and refuses discovered project `.codex/config.toml` files to avoid inadvertently loading project-supplied hook/MCP configuration. It ignores external exec-policy rules. These precautions do not make malicious repositories safe. Programs, test suites, build scripts and instructions in a repository are untrusted code/data.

Use a dedicated OS user, container, or VM for stronger protection. Do not use this release for hostile multi-tenant workloads. Never run it with access to valuable production credentials or files unless you have independently evaluated the exposure.

## Authentication and local adapter

Username/password are sent over HTTPS to the configured API. Plain HTTP is accepted only for loopback addresses. URL credentials, query parameters, fragments and redirects are rejected. Ambient HTTP proxies are deliberately disabled. The default HTTPS origin is a remote service even when the inference model is described as local.

Username and origin are saved in private `.state/config.json`. Passwords and bearer tokens are not intentionally persisted. Hidden password entry fails closed if the terminal cannot hide input. A temporary token lives in memory; best-effort logout runs at normal exit, handled errors and Ctrl+C. Forced termination, power loss, or network failure can prevent server revocation. Python/HTTP buffers are not guaranteed to be zeroized.

Automation environment passwords are removed before child launch; the launcher uses a small child environment allowlist. The shell environment excludes the adapter key and API credential fields. This does not protect against a malicious process with the same OS identity, a debugger, root, or arbitrary file reads of other secrets the OS user owns.

The adapter binds only to 127.0.0.1 on an ephemeral port, requires a cryptographically random per-session bearer key, checks Host, rejects browser Origin headers, disallows ambiguous request framing, and uses no access log. The engine receives the key in its environment, never as a command-line argument or config token. This mitigates unintended localhost use; it is not an OS-level security boundary against the same user.

## Model actions and data handling

Only whole JSON objects or fenced JSON envelopes can request tools. Arbitrary prose containing a JSON example is not scanned for execution. Tool names must have been offered to that request; namespaces, required fields and basic argument types are checked. This is not a complete JSON Schema validator. The engine's own validation and sandbox remain important.

Malformed Markdown escapes are repaired conservatively in protocol identifiers. Arbitrary shell commands and patch contents are not rewritten. Unknown tools, empty tool lists, duplicate JSON fields, invalid schemas and malformed output fail instead of silently pretending the task succeeded. Limits bound tool calls, repeated actions, model requests, context and wait times.

The launcher sends selected code, instructions and command outputs to the configured JV API. It does not redact all secrets from project files. Session histories can contain sensitive code/tool output even though authentication secrets are not deliberately stored. Treat `.state/` and backup archives as private; do not attach them wholesale to public bug reports.

## Retry and cancellation

Job creation is not automatically retried: a lost/invalid response might mean the job already exists. Polling GET requests use bounded retry/backoff and respect Retry-After without shortening it. Cancellation stops local waiting and the local agent process group; it does not implement a server cancellation endpoint. Inspect the last job ID before resubmitting. Processes intentionally detached from the process group and server-created jobs can outlive the CLI.

## Downloads

Downloads are opt-in. All descriptors are validated before downloading: same origin, exact job response-file route, bounded counts/sizes, safe names, regular files, no output overwrite, private temporary files and cleanup. Symlink paths are rejected and directory-descriptor operations reduce redirection races. Existing user-selected output-directory permissions are not changed. Downloaded content remains untrusted; it is never automatically executed.

## Installation, upgrades and integrity

Runtime installation is staged and version checked before replacement. Upgrades verify the incoming manifest, create source backups, preserve state/runtime/cache and roll back replaced source files on failure. Uninstall validates fixed owned paths and its launcher target before removal. Session locks prevent concurrent update/uninstall. Source checksums are not a signed software supply-chain attestation. npm, GitHub release publishing, and the configured API remain trusted external dependencies.

## Current limitations

This release has no penetration-test certification, verified production deployment, comprehensive same-user process isolation, persistent-service supervisor, or automatic update/security patch service. Read the acceptance report before rollout. Never respond to a sandbox failure by enabling a dangerous bypass flag.
