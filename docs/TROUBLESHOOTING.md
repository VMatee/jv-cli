# Troubleshooting

## Command not found

Normal installs create `~/.local/bin/jvcli`. If that directory is not in PATH, use:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Or call `$HOME/.local/bin/jvcli` directly. `./install.sh --add-path` may add one idempotent line to `~/.bashrc` when explicitly requested. Portable/development users can source `activate.sh`. Do not install an unrelated suggested `jcli` package.

## Username not configured / password requested again

Run `jvcli login`. Username and origin are saved after successful authentication. Tokens/passwords are not persisted, so each process asks again. That is intentional, not a login failure. For errors use `jvcli auth status`; it does not validate credentials online.

## Pinned engine absent / mismatched

From the actual installed folder run `./install.sh`. Node 18+, npm and Python 3.10+ are prerequisites. The installer only changes its local runtime. Do not globally upgrade npm just because it prints an update notice. No binary was prebuilt in this ZIP.

## Resume rejects --color

That regression is covered: the launcher only passes `--color never` on the initial exec. Run `jvcli --version` and verify 0.3.0. Check for a stale PATH or an older extracted folder. Old 0.2.x histories are not automatically migrated.

## Raw tool JSON printed / malformed tool response

Live diagnostics found Markdown-like damage to unfenced replies: array brackets were escaped, Python double-underscore names became bold markers, and quotes in code lost their JSON escaping. JV CLI now requests one fenced JSON block to protect the contents. It also accepts a standalone `JSON` language label immediately before that one complete block, as observed from the service. It does not strip arbitrary prose or guess how to reconstruct damaged code.

The adapter requires a complete, validated action envelope before exposing any tool call to the engine. It preserves decoded command/patch contents when handling invalid escapes or literal newlines/tabs inside JSON strings. Multiline custom patches can use an explicit `input_lines` list instead of one large escaped string. Missing quotes, truncated objects, unknown tools and invalid arguments are not guessed.

After a **confirmed completed** JV job returns invalid tool output, the adapter can request at most two corrected responses, showing each attempt and its job ID. These are additional model jobs and can consume quota. Earlier confirmed tool results remain in the prompt; rejected calls are not executed. Repeated invalid responses stop the turn with a nonzero exit and an inspection command:

```bash
jvcli job JOB_ID --json
```

This correction path does not resubmit a failed/ambiguous job creation or a failed poll. It cannot guarantee that the assigned model will produce usable tools. Do not share a complete job response without reviewing it for private project data.

If final text literally contains `\n`, this can be a double-escaped model response. The launcher does not blindly unescape all backslashes, which would damage code and paths.

## Generic error answer even though the JV job succeeded

The API's `succeeded` status means it completed a job, not that the coding task succeeded. The two observed generic responses beginning “I'm having a hard time fulfilling your request” and “I encountered an error doing what you asked” now use the same bounded correction path instead of counting as a successful coding turn. Specific explanations or refusals are still delivered normally.

If `jvcli ask "Reply with exactly: JV API OK"` works but coding fails, authentication/basic inference are working; structured tool output can still fail. `--allow-network` permits tool downloads, but does not repair model JSON. Use a fresh coding session after updating; inspect the final reported job if corrections are exhausted.

## Model claims the client workspace is not mounted

JV CLI's tools run on the user's PC; the API server does not need a mount of the user's project. A missing path in the server's environment is not evidence that the client workspace is missing. In live testing, the model confused these environments even after a successful local shell result.

The bridge instructions now explicitly distinguish the external client executor from the API server and ask for protocol messages, not server-side tool execution. Update JV CLI and start a fresh session rather than resuming the mistaken explanation. Do not move your project, expose your home directory to the server, or disable sandboxing to solve this response-format/context issue.

A syntactically valid final explanation can still be wrong, and an API job's `succeeded` status or CLI exit 0 does not certify the requested deliverable. Inspect actual tool results and tests; do not treat every refusal as a parsing error or retry it indefinitely.

## Command exit 128 from git log

An initialized repository with no commit makes `git log` fail. It is not necessarily an installation failure. Review the command/output and let the agent handle that state. Do not commit secrets or generated state just to silence an error.

## Waiting after a tool completes

The next model job may still be queued/running. The launcher prints waiting status periodically; the SSE adapter sends keepalives. The default per-job polling limit is five minutes; the whole coding turn is limited to one hour. Change the job limit with `JVCLI_WAIT_TIMEOUT=600 jvcli` for ten minutes. The engine SSE deadline is derived from the job budgets because comment keepalives do not reset its event-idle timer. Interrupting may leave a server job running. Check `/status` or the saved last job ID before resubmitting.

If the server reports `waiting_for_auth` after login succeeds, the submitted job is awaiting a server-side authentication step. Increasing a local timeout does not resolve that state. Inspect the existing job and have the server operator check provider authentication instead of creating duplicate tasks.

## Ambiguous job submission

Do not automatically retry. A job can have been created even if the response was lost or malformed. If an ID is available use `jvcli job JOB_ID`; otherwise inspect the service/account through its normal interface. The API example does not establish an idempotency or cancellation endpoint this wrapper can safely invent.

## Sandbox / kernel / network errors

Run `python3 -B scripts/engine_smoke.py` as a normal user. Keep its `.state/engine-checks/.../report.json`. Do not disable the sandbox to force the test to pass. This build cannot certify arbitrary Ubuntu/kernel/container configurations.

Network access from tools is disabled by default. A trusted project that needs downloads must be started with `jvcli --allow-network`; use a project-local virtual environment. Python's `venv` support may need a host prerequisite. Servers should bind 127.0.0.1, not the public interface.

## Existing project .codex/config.toml rejected

This build deliberately refuses to load project engine configurations that may enable hooks or MCP programs. Use a reviewed clean project copy. Do not blindly delete existing project configuration. Merely having a `.codex/` directory without that config file is not this check's trigger.

Your personal `~/.codex/config.toml` is not a project config and does not need to be removed or renamed. JV CLI ignores it and uses an isolated per-session `CODEX_HOME` under its own state directory.

## Problems after upgrade

Close all sessions. `./verify.sh` checks source integrity. The previous replaced source files are under `.backups/source-...`; state/runtime are not overwritten by the updater. Keep the previous ZIP for an explicit rollback. Never delete your active project to repair the launcher.

For a bug report provide the version, `doctor --json`, exit status, sanitized terminal output, and acceptance report. Do not share passwords, tokens, authorization headers, full session histories, private project code, or all of `.state/`.
