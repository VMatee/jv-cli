# Changelog

## 0.3.3 — 2026-09-06

- Make normal terminal output compact: preview long scripts, separate changed files and distinguish successful, failed and unknown command exits.
- Add `--verbose` for full commands, bounded output and more frequent waiting diagnostics. Keep JSONL output unchanged.
- Deduplicate unchanged waiting status to one reminder per minute, retaining job/status changes and correction notices.
- Separate final answers and wrap terminal prose without rewriting code blocks, inline code, URLs or tables; preserve redirected answer text.
- Request concise, structured final model answers with separate verification and run instructions. No changes to authentication, execution, network defaults or sandbox policy.

## 0.3.2 — 2026-09-06

- Enable tool networking by default for interactive, exec and resume workspace-write sessions.
- Add `--no-network` before or after exec/resume. Preserve explicit `--allow-network` compatibility.
- Keep read-only sessions network-disabled and reject explicit read-only/network-enabled combinations.
- Keep workspace write boundaries, credential isolation, engine 0.149.1 and no elevation/bypass unchanged. Network permission is not sudo permission.
- Validate the default and explicit policies in pseudo-terminals, option placement and conflicts, actual engine network access/denial and outside-workspace write denial with networking enabled.

## 0.3.1 — 2026-09-06

- Decode matching JSON fences of three or more backticks, including a standalone JSON badge and nested code examples. Mismatched/truncated envelopes do not execute.
- Add local, read-only `/permissions` and `/permission` interactive commands. Default network denial and sandbox policy are unchanged.
- Bound recognized Rust-discovery loops to six probes per turn; reject an over-limit batch atomically. Preserve existing action and request limits and canonicalize JSON argument ordering for repeated-action detection.
- Explain missing-tool blockers, per-command environment lifetime and explicit toolchain-installation authorization. Do not borrow another project's private tools.
- Keep engine 0.149.1 and existing authentication, transport timeouts, runtime isolation and update behavior.
- Add 17 automated cases (209 total, including one platform-dependent skip) and two real-engine acceptance cases. No Rust installation is performed by this release's validation.

## 0.3.0 changes from 0.2.3

This is the first public GitHub release baseline.

## Protocol and tool handling

- Added sandbox-aware Flask verification guidance: test_client by default, supplied TMPDIR instead of hard-coded shared /tmp paths, no force-delete cleanup, and bounded server lifecycle when real HTTP is needed.
- Added the observed “Sorry, something went wrong” template to exact generic-error detection; concrete refusals remain normal final replies. Added three regressions.

- Defaulted each model job's polling wait to five minutes, adjustable with JVCLI_WAIT_TIMEOUT. Derived the engine SSE idle budget from the job/correction budgets instead of the former two-minute cutoff; preserved the independent whole-turn deadline and disabled automatic submission retries.

- Fixed client/server execution-context confusion by explicitly treating JV tools as delegated tools on the external user's PC, not native server tools.
- Requested fenced JSON to protect code from the service's observed Markdown-like formatting; accepted the standalone JSON language badge before one complete fenced block without rewriting code.
- Verified the candidate against the live JV API: local Flask file creation, project-local dependency installation and six application checks succeeded in seven model jobs with zero corrections. Independent localhost HTTP checks also passed; no server was left running.

- Added bounded correction for malformed tool replies and the two observed generic provider error answers, only after confirmed succeeded jobs. Unknown tools/invalid schemas remain blocked; uncertain submissions are not resubmitted.
- Added multiline custom-tool `input_lines`, value-preserving literal newline/tab handling, smaller-action guidance, and removal of identical duplicated wrapper instructions.
- Reported correction attempts and the final JV job ID, recorded per-turn request/correction counts, and suppressed duplicate adapter error summaries.
- Added recovery regressions and real-engine checks for corrected patches, provider-error recovery, atomic rejection, and optional generated Flask application verification.

- Replaced permissive tool parsing with whole-envelope parsing, duplicate-key rejection, offered-tool validation, basic argument-schema checks, bounded recursion/calls and repeated-action limits.
- Kept narrow repair for Markdown-escaped protocol identifiers, without rewriting command/patch contents or arbitrary URLs/provider names.
- Preserved the second-turn `exec resume` fix: no `--color` after `resume`.
- Added explicit text-only compatibility boundaries and failures for unsupported Responses features instead of pretending they work.
- Stopped truncating tool JSON halfway through a schema. Added newest-request anchoring and explicit context-omission markers.
- Corrected success detection: engine exit 0 without completed turn/final text is not success.

## Authentication, transport and local safety

- Added random bearer authentication and Host/Origin validation to the localhost adapter.
- Isolated child environments and per-session engine homes; no adapter keys in config/argv.
- Added strict JSON, URL validation, no redirects/proxy inheritance, private atomic state writes and known-secret/terminal-control output handling.
- Reworked multipart uploads, response validation, bounded polling/backoff, ambiguous job submission errors, and explicit authenticated no-overwrite downloads.
- Added SSE start/keepalive while the backend job is pending. This is not true token streaming.
- Added limits, progress/error states, best-effort cancellation and failed-process-group cleanup.
- Removed any automatic bypass route; default workspace-write and tool network disabled, explicit read-only/network options.

## Usability and lifecycle

- Added per-session persistence, `sessions`, `resume`, `/status`, direct `ask/job`, JSON/JSONL output modes, and more informative doctor results.
- Added updater with source manifest verification, backups and rollback; preserves settings, runtime and caches.
- Staged engine installation before runtime replacement. A failed download preserves the old engine.
- Added default no-sudo installation under `~/.local/share/jv-cli` and a `~/.local/bin/jvcli` launcher.
- Preserved fully isolated `--portable` setup and terminal-scoped activation.
- Added opt-in, idempotent `--add-path`, guarded uninstall, deterministic ZIP/checksum packaging, checksum-first GitHub bootstrap installation, and release-tag automation.
- Added mandatory acceptance guidance, offline regression tests, real-engine scripted test, opt-in live API smoke test, and CI configuration.
- Corrected project-config detection so a personal `~/.codex/config.toml` is ignored while project-local configurations remain blocked.

## Migration and remaining limitations

Existing settings and old logs are preserved, but 0.2.x engine histories are not automatically migrated into new JV session metadata. Start a fresh session after updating.

This is still a Python wrapper plus a separately installed stock Rust engine. No JV Rust SDK or entire Codex source fork is bundled. Engine 0.149.1 compatibility and the scripted sandbox checks passed on the release host; actual model quality, all kernels, and ARM64 are not certified. Read TEST_REPORT.md.
