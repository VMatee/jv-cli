# Windows JV-INPUT-001 investigation — unresolved real-service gate

## Status

The client grammar interoperability defect is corrected, installed and tested.
The remaining real-service admission blocker is the dedicated account's incompatible
owner policy and fallback assignment. Real-service acceptance still fails. Do not
publish a replacement RC or claim the complete workflow resolved. Original RC tags
and assets remain unchanged.

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
The operator's subsequent read-only Linux investigation verified deployed
central_agent_api.py, frontend_service.py, central_store.py,
central_attachment_policy.py and central_wire_transport.py byte-for-byte against
this snapshot. The deployed central_correction.py and central_wire_retry.py were
also subsequently verified against it. No production files were changed from Windows.

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
  The locally generated idempotency key passes the exact server format validator.
  The Linux investigator confirmed zero Structured Agent Jobs and zero Structured
  idempotency records for the dedicated account; no successful registration occurred.
- The complete corrected body passes the snapshot normalize_request unchanged.
  No allowlisted detailed server reason was found in the disposable session logs.

The original class of real-service failure remains open. The account admission
incompatibility below is confirmed; the exact production exception was not captured.
Do not claim that grammar canonicalization completed real-service acceptance.

## Verified Linux production evidence

The operator reported these read-only findings on 2026-10-10:

- Host small-server-MS-7D09; combline-rpallms.service active/running, started
  2026-10-09 19:04:50 +07:00. Working directory:
  /home/small-server/Desktop/RPALLMs/ComblineRPALLMs.
- The seven relevant deployed files listed above match snapshot
  83d7a419e46d7db7c7d2792aefda65f0f925ebaa. Additional prompt-compilation
  dependency hashes are listed below for read-only comparison.
- The dedicated account authenticated. No Structured job or Structured
  idempotency registration survived either failed admission.
- provider-attempt-policy.json exists, is a regular mode-0600 file, predates
  service startup, has version 1/provider ChatGPT and a valid binding format.
  The operator confirmed that its owner does not match the dedicated account.
- The dedicated account's primary provider is ChatGPT. Its fallback policy is
  unavailable, not off. This violates the deployed fresh-wire admission rule.
- The effective production text limit appears to be the 102,400-byte default;
  a value loaded by the actual serving process has not yet been independently returned.

## Exact local pre-registration checks

The preserved disposable request was serialized using the actual CLI
JvApiClient.normalized_response_body, then passed through the snapshot's exact
pure functions, extracted without starting a server or worker. Private text was
kept in memory; only field names, sizes, counts and fixed outcomes were emitted.

- strict_json, Idempotency-Key syntax and normalize_request pass unchanged.
- The request declares background, input, instructions, model,
  parallel_tool_calls, store, stream, tool_choice and tools only. No engine-only
  fields, previous response, tool results, image/file parts or pending call exist.
- active_artifacts returns an empty list. Request-summary and API-origin
  validators pass. Account routing values are server-owned, not client overrides.
- Exact JV-WIRE-V1 compile_prompt produces 25,337 UTF-8 bytes. The literal
  transport override adds 823 bytes: final prompt 26,160 bytes, with 76,240 bytes
  of headroom under the reported 102,400-byte limit. This is the compiled provider
  prompt size, not merely the 17,221-byte HTTP JSON size.
- The detailed normalization, compilation and gate probe is retained locally
  under ignored .cache/pre-registration-probe.py. Its content-free results are
  .cache/pre-registration-probe-safe.log. It made no network request.

The probe executes the exact central_wire_retry.enroll function in isolated,
in-memory synthetic transactions. Ten incompatible policy/route cases reject:
missing owner policy, disabled policy, wrong version, missing/oversized binding,
provider mismatch, non-ChatGPT assignment, fallback enabled, remote execution,
and the dedicated account's confirmed combination of missing owner enrollment
and fallback unavailable (represented using synthetic identities only).
One eligible synthetic owner passes. Rejected transactions retain zero synthetic
jobs, idempotency markers and provider attempts. This tests the actual enrollment
predicate and SQL behavior; it is not a full HTTP replay or live-account observation.

## Confirmed account admission incompatibility

The source call chain is:
create_agent_response -> normalize_request -> compile_prompt/text-size check ->
CentralStore.register_job -> central_correction.enroll -> central_wire_retry.enroll.
For a fresh request, DEFAULT_MODEL_PROTOCOL is JV-WIRE-V1; protocol selection is
server-owned. No client-selectable model_protocol property is allowed.

Registration inserts the job and idempotency fields inside its transaction, then
enrolls before committing. The exact wire enrollment predicate requires an enabled
version-1 policy for that owner, a valid binding, matching ChatGPT provider,
fallback_policy == off and execution_target == local. A failed predicate raises:

"Wire agent mode requires the existing local ChatGPT owner/account binding with fallback off"

frontend_service.central_store_error maps that ValidationError to HTTP 400 /
JV-INPUT-001. The transaction rolls back and create_agent_response discards the
unregistered input. Zero durable records therefore do not rule out this gate.

The Linux investigator confirmed all remaining account flags:

| Condition | Verified result |
| --- | --- |
| policy_owner_matches_code | false |
| code_primary_provider_is_chatgpt | true |
| code_fallback_policy_is_off | false (policy is unavailable) |

Two independent enrollment requirements therefore fail: no matching owner policy,
and fallback_policy != off. Changing fallback alone cannot admit this account;
adding an owner policy alone cannot admit it while fallback remains enabled. The
exact preserved request passes the inspected request-shape validator, and this
verified assignment combination reproduces the enrollment ValidationError locally.
This is a proven account-policy admission blocker, not a hypothesis about grammar,
workspace spaces or accidental image attachments. The exact exception emitted for
the previous production request remains uncaptured; do not label the locally
reproduced static message as a captured production diagnostic. Prompt size passes
the reported default limit, not an independently inspected effective process value.

The deployed enrollment implementation agrees with its documented owner-scoped
wire contract. No client request rewrite can safely supply a different account
binding, override fallback or select a historical protocol. Do not implement any
such bypass or silently downgrade. The account cannot currently pass fresh Structured
admission; actual multimodal inference remains untested.

## Minimum safe Linux correction

Decide explicitly whether the dedicated account is authorized for Structured Mode.
If it is not, retain the admission restriction and return an accurate unsupported
account-capability error instead of generic malformed-input reporting.

If it is authorized, both failed conditions must be corrected through the supported,
reviewed Linux administration/deployment process:

1. Set the account's fallback policy to off through the supported assignment
   procedure while retaining its intended primary provider/model/effort. Do not
   silently switch accounts or reroute it. Retain unrelated secondary configuration;
   off controls whether fallback may run.
2. Establish an explicit valid owner/account binding for this account. Preserve the
   currently authorized owner. configure_agent_replacement_owner currently replaces
   the correction_policies map with one owner, so merely retargeting the existing
   file would displace that owner. Supporting both requires a reviewed server change
   for multiple explicit owners with no wildcard enrollment or weakened checks.
   Do not overwrite the existing policy as a troubleshooting shortcut.
3. Verify the policies loaded by the serving store, exact owner/provider match,
   version/enabled state, valid binding, fallback off, local execution and effective
   text budget. Do not assume current shell configuration is the running process's
   startup state. A routing-only change does not require retargeting the policy;
   any deployment/restart needed by reviewed multi-owner support is a separate action.

Server regression coverage must include two explicitly eligible owners without
displacing either, unenrolled owners denied, fallback unavailable denied even for
an enrolled owner, provider/binding mismatch denied, zero durable registration or
provider submission on denial, and a precise public capability error. Fresh
protocol selection, historical continuation, idempotency, binding isolation,
fallback prohibition and transaction rollback must remain unchanged.

These production corrections are not authorized from this Windows investigation. Do not restart
the server, change routing, switch accounts, weaken enrollment or replay the failed
session. Improving the server's public capability/error contract is a separate
repair: report account admission incompatibility distinctly from malformed JSON,
and expose eligibility without identifiers or binding values. Preserve the gate.

After an authorized correction is verified on Linux, perform one fresh, bounded,
secure-auth text admission test in a disposable Windows workspace. Do not resume
the retained failure or replay the original project request. Only after text and
tool execution succeed, test image continuation if the account is actually eligible.
No new Windows binary is warranted for an account-only correction. The valid CLI
grammar fix remains installed and awaits real acceptance before replacement RC2.

Additional snapshot SHA-256 values (not all independently verified on production):

| Source file | SHA-256 |
| --- | --- |
| central_wire_retry.py (Linux verified) | 5cdbbe9e50e0092ececfdd8f51359e2a5474ceff3876747a79caf10109946569 |
| central_correction.py (Linux verified) | c7f2371fc9fd8a2eb97a6ab860a0a281d0e001c578636ffd2f23d943046adde6 |
| central_wire_prompt.py | dfaef3620ca9de45b35f984912532438e6b95b8ff4a5a165620010969b359de5 |
| central_artifact_context.py | a37486a7550b8aba678f3b1c822056b5a4d94e1b4e7c6ff11c41870b90240cea |
| central_wire.py | b3acce671755d62947151a3da19e39c8a92f0d770db31eef5266132b6151ed6f |
| central_agent_validation.py | 01b5e24741540d5866bddb87a714064b345faa4315a1d8510a879e036c3cc1cf |
| central_input_artifacts.py | da6ee51bcfeabf3a0c575b964e527ddd8096ba39c0bd6b081469620c3cc21e76 |
| central_files.py | 7442699f2892c2a97445ceb19471c71ef1db3d673797e4a80eafe79c348f664c |
| providers/chatgpt/wire_literal.py | 1447973a7d05c85548ba2e652483e0f4b190e83e58ca74dcb94df4e106d4e1f4 |

## Required Linux/server read-only follow-up

1. Preserve the verified account booleans above. Verify the effective serving text
   limit and any remaining prompt-compilation source hashes if needed. The main
   validation and enrollment sources have already been independently compared.
2. Locate the dedicated test account's single most recent disposable first-turn
   failure. Return only endpoint, HTTP status, public code, static sanitized
   validation reason, serving revision and whether a durable job/idempotency
   record exists. Do not export tokens, passwords, prompts or raw logs.
3. Trace whether rejection occurred in register_job wire enrollment or an earlier
   gate. The compiled prompt is 26,160 bytes under the inspected snapshot. This
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
