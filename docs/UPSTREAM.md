# Upstream references and scope

Reviewed for this release on 2026-09-05.

## Codex engine

- Repository: https://github.com/openai/codex
- Pinned npm dependency: `@openai/codex@0.149.1`
- Source tag used for CLI/config compatibility inspection: `rust-v0.149.1`
- CLI contract: https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/exec/src/cli.rs
- Config schema: https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/core/config.schema.json
- Documentation: https://developers.openai.com/codex/config-reference

This pin preserves the version previously used by the user's 0.2.x installation; it is not a claim that 0.149.1 is the newest, safest, or universally working engine. Review upstream changes and repeat acceptance tests before changing it. Automatic engine upgrade is disabled.

`--color` belongs to initial `exec` and is not passed after `resume`. Prompts go over stdin using `-`. Shared JSON/skip-repository/rules options follow the pinned CLI contract. No sandbox-bypass option is injected.

The binary is installed on the user's host, not bundled in this ZIP. Its own package/license and bundled resources remain unchanged. The upstream Apache license and NOTICE are retained under `third_party/openai-codex/`. Our tests use fake engine fixtures unless explicitly running `engine_smoke.py` on a host with the real binary.

## JV API

- Repository: https://github.com/VMatee/jv-llm-api-example
- Python reference: https://github.com/VMatee/jv-llm-api-example/blob/main/python/jv_api_example.py
- Rust jobs reference: https://github.com/VMatee/jv-llm-api-example/blob/main/rust/src/jobs.rs
- Rust authentication: https://github.com/VMatee/jv-llm-api-example/blob/main/rust/src/auth.rs
- Default origin: https://ai.openjvspace.com

HTTP contract implemented: username/password login, temporary bearer token, X-JV-CSRF header, multipart job submission, queued/running/succeeded/failed polling, explicit conversation continuation in direct API mode, authenticated response-file downloads, logout. This package does not change or deploy the server.

The reference is a moving main branch. Compatibility was reviewed from published source; no live credentials were available for validating deployment-specific behavior. The Rust client code is not vendored and this ZIP does not update that GitHub repository.
