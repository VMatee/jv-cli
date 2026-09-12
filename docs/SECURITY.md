# Security boundaries

## Task evidence and completion (0.4.3)

The local bridge handles only a bounded metadata tool; shell, patch, plan and image tools still execute through stock Codex. Notes are model claims with checked provenance. Private task journals include a corruption-detection seal; it does not defend against an OS user able to rewrite both data and seal. A committed task is a model attestation, not objective domain correctness. No new provider credentials, OCR, Server-side file actions or sandbox privileges are introduced. See [AGENT_COMPLETION.md](AGENT_COMPLETION.md).


## What this build does and does not isolate

The normal installer uses `~/.local/share/jv-cli` for application, local npm engine, state, cache, and backups, plus a launcher symlink at `~/.local/bin/jvcli`. Portable mode keeps all of those in the extracted repository. It does not use sudo, global npm installation, system directories, or profile edits unless `--add-path` is explicitly requested. This is installation isolation, **not** a virtual machine, filesystem container, or guarantee that other projects cannot be affected by arbitrary programs.

For coding tools the launcher requests the pinned engine's `workspace-write` sandbox by default, with networking enabled, approval policy `never`, and no bypass switch. Use `--no-network` to disable tool networking. Network-enabled tools can send data to external services, so only use trusted workspaces and review tasks accordingly. The selected workspace is writable, plus the session's private tool HOME and temporary directory. `--read-only` requests read-only access with tool networking disabled. Network access grants neither sudo nor system-wide writes. Read access to other user-accessible paths is not represented as blocked. Runtime sandbox enforcement depends on the engine/kernel; the real-engine acceptance test must pass on each deployment class.

The launcher refuses obvious unsafe workspace roots (filesystem root, your home, the installation itself or its ancestors) and refuses discovered project `.codex/config.toml` files to avoid inadvertently loading project-supplied hook/MCP configuration. A personal `$HOME/.codex/config.toml` is deliberately ignored: JV CLI sets `CODEX_HOME` to its own per-session directory and does not modify the personal Codex installation or configuration. It ignores external exec-policy rules. These precautions do not make malicious repositories safe. Programs, test suites, build scripts and instructions in a repository are untrusted code/data.

Use a dedicated OS user, container, or VM for stronger protection. Do not use this release for hostile multi-tenant workloads. Never run it with access to valuable production credentials or files unless you have independently evaluated the exposure.

## Authentication and local adapter

Username/password are sent over HTTPS to the configured API. Plain HTTP is accepted only for loopback addresses. URL credentials, query parameters, fragments and redirects are rejected. Ambient HTTP proxies are deliberately disabled. The default HTTPS origin is a remote service even when the inference model is described as local.

Username and origin are saved in private `.state/config.json`. Passwords and bearer tokens are not intentionally persisted. Hidden password entry fails closed if the terminal cannot hide input. A temporary token lives in memory; best-effort logout runs at normal exit, handled errors and Ctrl+C. Forced termination, power loss, or network failure can prevent server revocation. Python/HTTP buffers are not guaranteed to be zeroized.

Automation environment passwords are removed before child launch; the launcher uses a small child environment allowlist. The shell environment excludes the adapter key and API credential fields. This does not protect against a malicious process with the same OS identity, a debugger, root, or arbitrary file reads of other secrets the OS user owns.

The adapter binds only to 127.0.0.1 on an ephemeral port, requires a cryptographically random per-session bearer key, checks Host, rejects browser Origin headers, disallows ambiguous request framing, and uses no access log. The engine receives the key in its environment, never as a command-line argument or config token. This mitigates unintended localhost use; it is not an OS-level security boundary against the same user.

## Model actions and data handling

Legacy coding mode remains the default and retains the strict text-envelope behavior described below. Opt-in structured mode (`JVCLI_AGENT_API=1`) does not use that envelope or its repair prompts. It sends native text/initial-image messages plus the certified local tool schemas to JV's asynchronous Responses API. On the current production Server, model-authored structured actions are transported internally as JV-WIRE-V1; only validated Responses-shaped output reaches JVCLI, and raw wire text is never executed by the client.

Before a structured POST, JV CLI atomically records a unique idempotency key and normalized request body. An ambiguous POST is reconciled only by replaying that same body with that same key. Polling is repeatable; local timeouts do not cancel server work. Response IDs, output IDs, call IDs, lifecycle state, declared tool name, JSON arguments and continuation history are validated before any executable event is published.

A structured tool call is journaled as published before it reaches Codex. Repeated polling or a repeated local request cannot publish it twice. A restart with an unresolved published call fails safely unless Codex supplies the exact call and a matching `function_call_output`; changed or unexpected IDs/calls/results are rejected. This prevents blind duplicate execution but is not a claim of exactly-once local side effects: a crash can leave the client requiring manual reconciliation.

In legacy coding mode, only whole JSON objects or fenced JSON envelopes can request tools. Arbitrary prose containing a JSON example is not scanned for execution. Tool names must have been offered to that request; namespaces, required fields and basic argument types are checked. This is not a complete JSON Schema validator. The engine's own validation and sandbox remain important.

A single complete fenced block may have the standalone language label `JSON` immediately before it. This narrowly handles the service's observed code-block presentation; surrounding explanations, multiple blocks and malformed/truncated JSON do not become executable tools. Code contents are not Markdown-decoded to reconstruct lost underscores, quotes or indentation.

Prompts distinguish the external client executor from the inference server. This is a compatibility instruction, not a guarantee about server-side behavior. Never mount additional local data on a remote server just because a model claims a client path is missing there.

Malformed Markdown escapes are repaired conservatively in protocol identifiers. Arbitrary shell commands and patch contents are not rewritten. Unknown tools, empty tool lists, duplicate JSON fields, invalid schemas and malformed output fail instead of silently pretending the task succeeded. Limits bound tool calls, repeated actions, model requests, context and wait times.

Literal newlines/tabs inside JSON strings retain their decoded values; a custom tool may supply `input_lines`, joined with newlines. Ambiguous/truncated JSON is not completed by guessing. Every call in a batch must validate before any is exposed to the engine. In legacy coding mode, after a confirmed succeeded job returns an invalid envelope or an exact known generic error answer, the adapter may create up to two correction jobs. The same tool catalog, workspace restrictions, cancellation and overall request/turn limits apply. This is not a retry of an uncertain submission, a replay of executed tools, or a bypass for a concrete refusal. Raw rejected answers are not added to local logs or correction prompts.

The launcher sends selected code, instructions and command outputs to the configured JV API. It does not redact all secrets from project files. Session histories can contain sensitive code/tool output even though authentication secrets are not deliberately stored. Treat `.state/` and backup archives as private; do not attach them wholesale to public bug reports.

## Retry and cancellation

Job creation is not automatically retried: a lost/invalid response might mean the job already exists. Polling GET requests use bounded retry/backoff and respect Retry-After without shortening it. Cancellation stops local waiting and the local agent process group; it does not implement a server cancellation endpoint. Inspect the last job ID before resubmitting. Processes intentionally detached from the process group and server-created jobs can outlive the CLI.

Structured creation differs because the public contract supplies idempotency. The client may make one immediate reconciliation replay after an ambiguous POST, using the already-persisted key and byte-equivalent normalized body. Further invocation resumes that same prepared/submitted round; it never invents a new key for the uncertain work. A new continuation receives a new key.

## Downloads

Downloads are opt-in. All descriptors are validated before downloading: same origin, exact job response-file route, bounded counts/sizes, safe names, regular files, no output overwrite, private temporary files and cleanup. Symlink paths are rejected and directory-descriptor operations reduce redirection races. Existing user-selected output-directory permissions are not changed. Downloaded content remains untrusted; it is never automatically executed.

## Installation, upgrades and integrity

Runtime installation is staged and version checked before replacement. Upgrades verify the incoming manifest, create source backups, preserve state/runtime/cache and roll back replaced source files on failure. Uninstall validates fixed owned paths and its launcher target before removal. Session locks prevent concurrent update/uninstall. Source checksums are not a signed software supply-chain attestation. npm, GitHub release publishing, and the configured API remain trusted external dependencies.

## Current limitations

This release has no penetration-test certification, comprehensive same-user process isolation, persistent-service supervisor, or automatic update/security patch service. Production acceptance is scoped to the documented Scenario 01 run and does not certify every workload, account assignment, model, operating system, or deployment environment. Read the acceptance report before rollout. Never respond to a sandbox failure by enabling a dangerous bypass flag.

## Initial image boundary

The `--image` option reads only regular files beneath the selected workspace, rejecting parent traversal and symlinks through directory-descriptor traversal. Codex receives private snapshots. The bridge accepts bounded inline PNG/JPEG/WebP data only, never filesystem paths or remote URLs. Full image decoding and attachment lifecycle remain server responsibilities. Base64 data URLs are redacted from diagnostics; private session journals and snapshots contain image bytes and must not be published. This ingress rule does not claim that all arbitrary engine reads outside the workspace are blocked.

## Certified image and custom tool results

Image results remain function_call_output arrays with their exact call association, never user-message substitutes. Only 1–4 inline PNG/JPEG/WebP image items are accepted per result array; historical results remain integrity-checked, while the coordinated Server extension keeps at most four active images and 12 MiB. Evicted observations retain metadata, never invented visual descriptions. Custom apply_patch grammar is digest-pinned, freeform input is never rewritten or executed by the bridge, and its string result is limited to 32 KiB. Durable state validates call class as well as call ID and exact payload. Server attachment lifecycle and decode remain server-owned.
