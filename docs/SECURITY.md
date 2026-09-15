# Security and privacy

## Project access

Start JV CLI in a dedicated project directory. Normal sessions can change files there and run project tools with network access. Use `--read-only` for inspection or `--no-network` when project tools should not contact external services. These options do not grant administrator privileges.

Workspace protection is not a complete guarantee that every readable file outside your project is inaccessible. Keep unrelated sensitive files out of tasks and review any proposed work that accesses additional locations. Do not disable protection to bypass an error.

## Data sent to the service

Your prompts, selected project content, attachments, and command results may be sent to your configured JV service to complete a task. JV CLI does not automatically remove every secret from source files. Submit only information you are authorized to share.

Saved sessions and application backups can contain private code, results, and images. Protect them locally. Do not attach entire state directories or raw logs to public issues.

## Accounts

Password entry is hidden. The application intentionally saves only your account name and service address, keeping authentication tokens in memory during use. Never put passwords on the command line, commit credentials, or share tokens in support requests. Approved automation should obtain secrets through a protected secret manager.

HTTPS and certificate verification are required for remote service connections. Loopback HTTP is intended only for local testing.

## Output and retries

Review generated changes, run appropriate tests, and inspect final artifacts. Completion messages are not independent proof of correctness. Failed or interrupted commands may have partially changed files.

A timeout does not prove that remote work stopped. Check the known request before resubmitting. Session recovery can require manual review after an interrupted operation; do not edit saved state to force continuation.

## Downloads and updates

Download releases from this repository and verify their checksum before extraction. Downloaded task output is untrusted and is not automatically executed. Existing output files are not silently overwritten.

Close active sessions before updating. The installer verifies incoming application files, preserves account/session data, and backs up replaced source. Checksums detect changed bytes but are not a signed security attestation.

## Responsible use

Automated checks do not certify every operating system, account configuration, workload, or live service. Never use elevated privileges or disable system security merely to make a test or task pass. Report suspected security issues privately to the repository owner without including live credentials or user content.
