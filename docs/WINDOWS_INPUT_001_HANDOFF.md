# Windows JV-INPUT-001 investigation — unresolved real-service gate

## Status

The client grammar interoperability defect is corrected, installed and tested,
but real-service acceptance still fails. Do not publish a replacement RC or claim
the incident resolved. Original RC tags and assets remain unchanged.

Accepted baseline CLI: fdf3328ddc83fa07b6f461362bbe17f3785435f8.
Corrected CLI: ffe028d76bf20ba893e54fb0295cfd45bcb54936 on
fix/windows-structured-grammar, version 0.5.3, engine 0.149.1, bridge protocol 1.
Desktop is unchanged at c8b1083d93f07850750bd6f4bcd7f4d0b82b51e3, version 0.2.3.
Both installed binaries were verified; the original user project was not modified.

## Proven client defect

Windows Codex embeds the certified apply_patch Lark declaration with CRLF.
The original installed CLI forwarded it unchanged: SHA-256
ce2574fac05867f519a0ce3bdae50ce7d68b6d2e5f68d3c0c7e75518142d89b3.

Read-only GitHub source snapshot VMatee/jv-platform commit
83d7a419e46d7db7c7d2792aefda65f0f925ebaa,
server/ComblineRPALLMs/central_agent_api.py, accepts only CERTIFIED_LARK_SHA256
 d6367f4826ed608c424b0a308f3d6163527df63c22513d089b91863552f8bfeb
(the exact LF version). normalize_request rejects CRLF with:
"Unsupported custom format; only the certified pinned Lark definition is accepted".
frontend_service.py maps ValidationError to HTTP 400 / JV-INPUT-001.
This validation precedes new job registration in the inspected source.
The snapshot's deployed status has not been established.

The original failed bodies were checked in memory against the snapshot's actual
pure validator functions; private prompt text was not printed or copied. Both
failed on this grammar rule and passed after changing only the grammar declaration
line endings. A synthetic-content reproduction produced the same result.

Fix: validate the original engine declaration against exact platform-certified
hashes, then canonicalize only its declaration CRLF to LF, and assert the canonical
hash. Never normalize freeform patch input, mutate engine history, accept altered
or mixed grammars, disable view_image or change security policy.

Changed shipped source: lib/jvcli/structured.py.
Regression coverage: tests/test_windows_grammar.py (two additional tests and
updated existing test); MANIFEST.sha256 synchronized. Tests assert exact wire
hash, five-tool preservation, no source mutation and rejection of uncertified
line endings. No Desktop or server implementation was changed.

## Results

- Windows preflight: 92 passed.
- Native checks: 214 passed, zero skips.
- Full Windows bridge/trusted gate passed, including three grammar tests,
  image/history, journal, process cleanup and real tool network cases.
- Source and corrected installed CLI synthetic vision each passed PNG/JPEG/WebP,
  follow-up edit, two turns, restart/resume, unsupported single submission and
  explicit fresh Legacy session.
- Official installer/portable acceptance passed: 17 inner checks, 19 bundled
  module provenance checks, six network cases, install/rollback/reinstall,
  portable integrity and uninstall/PATH/state retention.
- Corrected CLI installed normally after official acceptance; BUILD.json confirms
  ffe028d76bf20ba893e54fb0295cfd45bcb54936.
- Exact-commit CI passed:
  https://github.com/VMatee/jv-cli/actions/runs/38044952660

Locally prepared, NOT PUBLISHED assets:

| Asset | SHA-256 |
| --- | --- |
| jv-cli-0.5.3-windows-x86_64-setup.exe | 0fdc9c5c04bba3fb1375f3922b80173803c091f8374c8c94944adef94c122fa9 |
| jv-cli-0.5.3-windows-x86_64.zip | 78c01bafa309d0faafeecc0abb522afb871d48050e0bf3b9e2aa8f3d9734efb5 |

Metadata and official inventory verification passed in .cache/grammar-fix-assets.
No windows-rc-0.5.3-2 tag was created. Do not publish these files until the real
acceptance gate passes. Existing public RC 1 remains immutable.

## Controlled real-service failure after correction

The operator selected a disposable workspace and entered credentials locally
through the normal Desktop form for the dedicated test account. The driver never
read password fields or authentication headers. It submitted one harmless text-only
admission check. That turn failed with JV-INPUT-001. No retry was made and the
conditional visual-coding task was NOT submitted. Real image capability is unknown.

Saved evidence in Desktop (ignored): .cache/real-contract-KIRnPk/report.json and
.cache/real-contract-run.log. The exact disposable workspace is recorded there.
The session journal was inspected only for safe request structure and submission
metadata; original project sessions were not replayed or changed.

The new failed request:

- POST /v1/responses; public code JV-INPUT-001 (mapped HTTP 400 by the snapshot).
  The original raw HTTP status/reason was not captured by this GUI driver.
- Canonical grammar hash d6367f4826ed608c424b0a308f3d6163527df63c22513d089b91863552f8bfeb.
- 17,221 serialized UTF-8 bytes; three text messages; five tools: shell_command,
  update_plan, apply_patch, view_image, jv_record_evidence.
- All strict function object schemas recursively require every declared property.
- model jv-ai; background/store true; stream/parallel_tool_calls false;
  tool_choice auto; no previous_response_id; no image/file attachment.
- Durable state phase prepared, no response ID, zero uncertain-submission retries.
  A locally generated idempotency key exists. Server acceptance of the key and
  absence of a remote durable record cannot be independently confirmed locally.
- The complete corrected body passes the snapshot normalize_request unchanged.
  No allowlisted detailed server reason was found in the disposable session logs.

The original class of real-service failure remains open. Current evidence does
not identify the remaining deployed validation rule, account routing constraint
or deployment revision. Do not guess or silently downgrade to Legacy.

## Required Linux/server read-only follow-up

1. Identify the actual serving central revision and compare central_agent_api.py,
   frontend_service.py and central_store.py with the snapshot above. Do not assume
   the GitHub main commit is deployed; account for the active serving node.
2. Locate the dedicated test account's single most recent disposable first-turn
   failure. Return only endpoint, HTTP status, public code, static sanitized
   validation reason, serving revision and whether a durable job/idempotency
   record exists. Do not export tokens, passwords, prompts or raw logs.
3. Trace whether rejection occurred in normalize_request, compiled-context size,
   register_job routing/account validation or a different deployed rule. This
   first request had no artifacts, so do not infer an image-account restriction
   from the presence of a view_image tool declaration alone.
4. Reproduce the deployed rule offline against a synthetic request with the same
   fields/tool schemas. Confirm an actual contract difference before proposing
   any further client/server fix. Production deployment requires its own process;
   nothing was modified on Linux from this Windows investigation.
5. Reconcile the previous submission before another test. If an accepted job
   exists, poll/reconcile it instead of resubmitting. If definitively rejected,
   perform one fresh bounded secure-auth admission check after correction.
6. Only after real text admission/tool execution succeeds, run the bounded
   PNG/JPEG/WebP visual-coding acceptance if the actual account supports it.
   Preserve explicit Legacy selection and never silently change accounts.
7. Complete Windows installed acceptance for any additional change; publish only
   changed components under unused RC tags after native, real and CI gates pass.

Linux Phase 3 source investigation can proceed using the preserved histories.
Official cross-platform publication must wait for this unresolved real-service
integration gate; the earlier synthetic-only Phase 2 completion report does not
establish live-provider compatibility.
