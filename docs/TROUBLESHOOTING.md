# Troubleshooting

## `jvcli` is not found

Add the per-user command directory to your current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
jvcli --version
```

You can also run `$HOME/.local/bin/jvcli` directly. Use `./install.sh --add-path` only if you want the installer to update your shell startup file.

## Installation is incomplete

Check that Python 3.10+, Node.js 18+, and npm are installed and network access is available. From the trusted installed or extracted application directory, run `./install.sh`, then `jvcli doctor`. Do not install an unrelated similarly named system package.

## The password is requested again

This is expected: JV CLI saves your username and service address, not your password. Run `jvcli login` to check account setup. `jvcli auth status` displays saved configuration but does not verify credentials online. Ask your administrator about account restrictions; do not share passwords in support reports.

## A request takes too long

Increase `JVCLI_WAIT_TIMEOUT` if your service needs more time. A timeout or connection loss may leave remote work running. Check its known ID or saved session before starting another request; repeated submissions can duplicate work and consume quota.

## A task stops with an error

Read the final error and review the files and test results already produced. Failed or interrupted commands can leave partial file changes. Inspect affected files before continuing. Do not treat file existence or a completion message as proof that output is correct.

Malformed or unsupported responses stop safely. Keep the error code and version for support, but omit credentials and private project content. Repeated retries will not resolve an unsupported capability.

## File writes or networking are denied

Use `/permissions` to check the current session. `--read-only` denies writes and project-tool networking. `--no-network` disables project-tool networking while preserving workspace edits. Restart with the intended flags; `--allow-network` cannot be combined with `--read-only`.

If system protection prevents a task from running, collect `jvcli doctor` output and contact support. Do not disable system security or grant administrator access merely to force a task through.

## A saved session cannot resume

Use the same directory, account, service address, and optional task mode. Close another process using that session. Older incompatible sessions may require a fresh task; preserve their files rather than modifying them manually.

## An image or attachment is rejected

Check the file type, size, account capability, and path. Image-assisted tasks accept up to four PNG/JPEG/WebP images inside the workspace and reject symlinks. A filename extension alone does not make a format supported. Ask your administrator whether the required capability is enabled.

## An update is refused

Close running JV CLI sessions and verify the new package before retrying. Preserve any locally modified source files. Never overwrite a modified checkout or delete application state to make an update proceed.

## Reporting an issue

Include the version, operating system, command with sensitive arguments removed, error code, and a minimal reproducible example. Review diagnostics before sharing. Do not upload whole session directories, logs, private files, tokens, or passwords.
