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

This release narrowly repairs malformed Markdown escapes in identifiers, validates that the requested tool was offered, and rejects malformed action envelopes. It does not execute a tool guessed from arbitrary prose. A model that repeatedly returns invalid envelopes needs prompt/model/server evaluation; permissive parsing is not a safe universal repair.

If final text literally contains `\n`, this can be a double-escaped model response. The launcher does not blindly unescape all backslashes, which would damage code and paths.

## Command exit 128 from git log

An initialized repository with no commit makes `git log` fail. It is not necessarily an installation failure. Review the command/output and let the agent handle that state. Do not commit secrets or generated state just to silence an error.

## Waiting after a tool completes

The next model job may still be queued/running. The launcher prints waiting status periodically; the SSE adapter sends keepalives. Default local wait and turn limits are one hour. Interrupting may leave a server job running. Check `/status` or the saved last job ID before resubmitting.

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
