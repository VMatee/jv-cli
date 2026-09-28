# Changelog

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
