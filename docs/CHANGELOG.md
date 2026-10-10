# Changelog

## 0.5.3 — release candidate in preparation

- Support explicit Structured bridge sessions for image-assisted coding with
  PNG, JPEG and WebP, followed by further edits and tests in the same session.
- Preserve explicit Legacy selection and report unsupported Structured services
  without an automatic fallback submission.
- Windows installer acceptance and release publication are pending.

## 0.5.2 - remote support codes and recovery status

- Carry the same remote support-code reporting and same-job recovery intended for 0.5.1.
- Correct release publication permissions so the existing verification gate can read Actions results before publishing packages.
- Keep Linux and Windows execution policies unchanged.

## 0.5.1 - unpublished tag: remote support codes and recovery status

The tag was published, but its workflow stopped before any GitHub Release assets
were published. See the [release history note](RELEASING.md#unpublished-051-tag).

- Forward validated public JV support codes so compatible clients can show a code when remote work fails.
- Report administrator authentication attention without ending the active turn. Continue polling the same remote job after recovery, without automatic resubmission.
- Show only reviewed public explanations; keep provider diagnostics private and clear remote error state before the next turn.
- Preserve bridge protocol 1 compatibility and existing Linux and Windows execution policies.

## 0.5.0 - native Windows workers

- Add per-user Windows AMD64 installation and a portable ZIP with the required runtime included.
- Support explicit trusted-host execution on dedicated Windows worker accounts: full tool filesystem access, network enabled, and no approval prompts.
- Preserve separate private state, saved sessions and bounded bridge/process cleanup.
- Keep Linux installation and permission modes unchanged.
- Windows requests requiring network isolation remain unsupported and fail closed.

## 0.4.9 — machine stdio bridge

Adds the Linux `jvcli bridge --stdio` NDJSON interface with memory-only bridge
authentication. Existing terminal interfaces remain compatible. Bridge images
remain deferred.

## 0.4.8 — offline installation package

- Add a Linux x86_64 offline ZIP containing JV CLI source, the pinned agent engine, and Node.js.
- Verify the offline runtime files before installation and check the bundled engine before replacing an existing runtime.
- Keep the normal smaller online ZIP available. Using AI tasks still requires a connection to the JV service.

## 0.4.7 — interactive command suggestions and Thai input

- Show live English slash-command suggestions with Thai descriptions, Tab completion, and arrow-key selection in an interactive terminal.
- Suggest likely spellings for unknown slash commands without sending them as model tasks.
- Add interactive `/logout` to forget the saved account; `/exit` continues to keep it.
- Preserve Thai task input and ask the assistant to answer in the task's language when practical.

## 0.4.6 — clearer execution failures

- Distinguish remote output rejection and provider cleanup failures from project tool errors.
- Keep failed remote responses stopped without automatic resubmission; preserve completed tool results and saved sessions for diagnosis.
- Display fixed error descriptions instead of remote error text.

## 0.4.5 — clearer setup and usage guides

- Reorganized installation, account setup, everyday commands, updates, and troubleshooting into shorter user guides.
- Refreshed release downloads and feature-focused release notes.
- No changes to task execution, account behavior, workspace permissions, or supported features.

## 0.4.4 — more careful completion review

- Task completion guidance now calls for rechecking files that may have been partially changed by failed or interrupted commands.
- Checking only that a file exists or is nonempty is insufficient verification.
- Improved guidance when starting fresh from an incompatible saved session.

Always review important generated files and run your project's checks. These improvements do not guarantee output correctness.

## 0.4.3 — more reliable saved work

- Improved task progress tracking and completion review.
- Better continuity for saved sessions and image-assisted tasks.
- Added regression coverage for recovery and repeated operations.

## 0.4.0 — optional image-assisted tasks

- Added an opt-in task mode for accounts with compatible service capabilities.
- Supported initial workspace images and continued work with saved sessions.
- Preserved direct questions, attachments, and generated-file downloads.

## 0.3.x — terminal usability and installation

- Clearer command output, detailed diagnostics with `--verbose`, and permission status commands.
- Network-enabled workspace tasks by default, with `--no-network` and `--read-only` controls.
- Per-user installation, portable setup, saved sessions, verified updates, and guarded uninstall.
