# JV CLI contributor guide

Read `README.md`, the relevant source and tests, and this guide before making changes. `VERSION` is the canonical version.

## Preserve local work

Inspect status, branch, history, remotes, staged changes, and untracked files before fetching. Preserve local work and independent history. Never discard dirty files, replace branches destructively, or force push without separate authorization. Commit or publish only within the user's requested scope.

## Public documentation

Write for people installing and using JV CLI. Explain features, prerequisites, commands, account setup, permissions, updates, and actionable errors. Keep implementation architecture, dependency-version commentary, internal acceptance records, and operational investigations out of customer guides and release notes. Required license and third-party notices must remain intact. Do not imply unsupported features or unverified behavior.

## Changes and safety

Keep changes focused, preserve existing functionality, and do not upgrade pinned dependencies as part of unrelated work. Respect workspace permissions, explicit network denial, read-only operation, credential isolation, and session integrity. Never weaken protections to pass tests.

Do not read or commit real credentials, private keys, sessions, request content, or runtime state. Keep generated caches, environments, local configuration, downloads, and package output out of Git. Use temporary homes and synthetic accounts for tests; never alter the user's installation or contact the live service just to check a change.

## Validation and packaging

Inspect the package inventory, then run:

```bash
./scripts/build-release.sh
./test.sh
./verify.sh
```

For release or execution changes, run the relevant integration scripts under `scripts/` with the existing supported dependencies. Verify the ZIP checksum, extract and verify the package, and test installation/version/diagnostics with a temporary home. Keep `MANIFEST.sha256` synchronized with all shipped files. Report real results and distinguish local automated checks from live service acceptance.

## Publishing

Use the existing repository-specific SSH authentication without exposing keys. Review the complete staged diff and file list. Publish normally, never force-push. Do not create tags or releases without authorization. Keep `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and all bundled upstream license/notice files. User documentation edits do not authorize removing attribution or changing implementation identifiers.
