# Milestone 3B: adversarial bridge review

Development review of feature baseline `02d990f926be2efb9fac47e4915da1d9c8215fd5`
against main `f8c3541dce9898c46f72628d98512f20ca09c864`. Version remains 0.4.8.
This is offline evidence, not production acceptance or merge authorization.

## Method

Read the bridge, transport, engine runner, shared session context, safety helpers,
protocol document, fixtures, and packaging rules before production edits. Record
candidate issues first; reproduce each changed behavior with deterministic tests.
Keep tests in temporary HOME/JVCLI_HOME and a Bubblewrap private network namespace.
The read-only host mount and writable repository bind keep fixture writes isolated.
No JV account or production endpoint is involved.

## Findings and resolutions

### HIGH — SIGTERM skipped owned-process and token cleanup

- Component: bridge process lifecycle.
- Evidence: `test_sigterm_active_engine_cleans_up` failed on baseline with exit
  `-15`; the default signal action skipped runtime close/logout while the engine
  was running in its separate process group. Test cleanup explicitly killed the
  synthetic group, preventing an orphan during reproduction.
- Impact: normal parent termination could leave local work running and skip logout.
- Resolution: bridge-only SIGINT/SIGTERM handlers set stop flags; the owner performs
  cancellation and cleanup, exiting 2. Handlers acquire no locks and do not unwind
  partially constructed session state. Existing terminal behavior is untouched.
- Tests: active SIGTERM, idle SIGINT, signal during slow authentication, existing
  process-tree EOF/cancellation and active shutdown tests.

### MEDIUM — fragmented input starved lifecycle processing

- Component: `LineReader.next`.
- Evidence: continuous small partial writes prevented `turn.completed` from being
  reaped; `test_partial_input_does_not_starve_turn_completion` timed out on baseline.
- Impact: delayed completion and detection of failed stdout despite bounded memory.
- Resolution: yield to the owner after each incomplete read; retain bounded framing.
- Tests: trickled input during a turn, fragmented UTF-8, multiple messages per chunk,
  oversized-line recovery, final line without newline, deep/invalid JSON.

### HIGH — authentication lacked an overall deadline

- Component: synchronous bridge authentication/logout.
- Evidence: existing client timeout is an idle socket timeout, not an end-to-end
  deadline for response reads. A deterministic delayed fake login blocked the
  bridge beyond its intended operation budget; the new deadline test failed before
  the fix and succeeds afterward.
- Impact: slow client/network operations could delay shutdown/EOF/fatal-output
  handling indefinitely from the protocol owner's perspective.
- Resolution: bridge-only Linux main-thread deadlines (login 30 seconds, logout
  5 seconds), without an authentication worker or changes to shared terminal
  authentication semantics. Local token references are cleared in logout's finally.
- Tests: slow login timeout/recovery, signal while login is pending, login failure,
  replacement, logout failure and lifecycle cleanup. Kernel-level uninterruptible
  calls and unknown server-side state after interrupted login remain documented
  limitations, not claims of secure erasure or guaranteed remote revocation.

### MEDIUM — corrupt thread metadata escaped the outbound schema

- Component: `session.started` resume acknowledgement.
- Evidence: replacing a synthetic saved `thread_id` with a nested object caused
  that object to be emitted. `test_resume_rejects_non_identifier_thread_metadata`
  failed before the fix.
- Impact: arbitrary saved metadata could escape the narrow, typed event boundary.
- Resolution: validate the candidate thread ID before assigning the active session;
  close the candidate and return sanitized `invalid_session` on invalid data.
- Tests: object, integer, newline and oversized thread IDs; valid resume remains
  supported. No terminal metadata format or shared resume-binding rule changed.

### HIGH — option-shaped engine thread identifiers

- Component: engine thread ID persistence/resume argument boundary.
- Evidence: a synthetic saved `thread_id` of
  `--dangerously-bypass-approvals-and-sandbox` passed the old identifier check.
  `test_resume_thread_cannot_be_an_engine_option` failed before hardening; the
  shared runner places a saved thread ID directly after `exec resume` in argv.
- Impact: native argv avoids shell interpolation but still permits option
  interpretation when a positional value begins with a hyphen. No real engine
  bypass was exercised; acceptance of the option-shaped value was reproduced.
- Resolution: reject leading-hyphen thread IDs both from saved metadata and engine
  `thread.started` events before they can be used for bridge resume. Request IDs
  and terminal CLI behavior are unchanged.
- Tests: corrupt saved option-shaped ID rejection; synthetic engine option-shaped
  ID causes `turn.failed`, is not persisted, and does not enter subsequent argv.

## Reviewed decisions and limits

- Retain coarse `invalid_session`: no demonstrated need to reveal finer filesystem,
  engine or account details. Raw exceptions/server bodies remain suppressed.
- Request IDs are correlation labels, with no replay database. Generated turn IDs
  identify turns even when request IDs are reused.
- One active turn remains enforced through cleanup. A completed/cancelled race
  yields one terminal outcome; cancelling after completion yields `cancel_error`.
- A deliberately hung worker produces fatal exit after 15 seconds without closing
  its session concurrently. The synthetic hang test spawns no engine. It verifies
  no runtime close/logout races or false success. Restart is required; local or
  server cleanup cannot be guaranteed for an arbitrarily wedged worker.
- Display paths remain text, including absolute/traversal/Windows-looking paths.
  Normalization grants no filesystem authority and does not open those paths.
- A closed/backpressured pipe may end with a partial transport write. Receivers
  must discard an unterminated final fragment; successfully delivered frames are
  bounded JSON objects. No protocol can guarantee delivery after disconnection.
- `bridge` is an explicit reserved subcommand. Bare `jvcli bridge` is an invocation
  error; terminal policy flags are rejected before protocol startup.
- Linux only. SIGALRM deadlines, fcntl locks and process groups are not Windows
  support. No Desktop changes or production acceptance are included.

## Validation inventory

The original 331 terminal/core tests and 21 bridge tests remain in place. The new
adversarial suite adds 25 tests. Coverage includes request/state/version matrices,
malicious IDs, hostile JSON/framing, argv/stdin/metadata separation, signal cleanup,
timeouts, cancellation races, failed setup/worker/context/logout, hung workers,
resume corruption/account/origin/policy checks, workspace restrictions, terminal
session listing, normalization limits, and oversized output rejection.

Required gates: complete unittest discovery, `./test.sh`, `./verify.sh`, release
build, ZIP checksum/extraction/manifest verification, extracted bridge suites,
isolated installation/version/help/diagnostics, and scripted pinned-engine smoke.
No release, merge, tag, installed-CLI change, or live test is authorized by this
review. Final gate outcomes are reported with the feature-branch publication.
