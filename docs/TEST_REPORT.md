# JVCLI 0.4.3 verification and production acceptance

Canonical JVCLI source is 0.4.3 and stock Codex remains exactly 0.149.1.
GitHub publication remains a separate release gate.

## Live production acceptance — 2026-09-12

Scenario 01 completed with `SCENARIO_RC=0` through the coordinated JV-WIRE-V1
ChatGPT browser/RPA path. Alice graded 10/10, Bob 8/10, and Charlie retained
8 confirmed points with Q3 `REVIEW_REQUIRED`; the ambiguous answer was not
invented. OCR was not used and the source PDFs remained unchanged.

The accepted run completed provider jobs with `cleanup_status=reset`. One response
encountered a Copy control whose computed `pointer-events` was `none`; the bounded
exact-locator keyboard compatibility path captured it successfully, followed by
post-response model verification, Temporary Chat verification and reset cleanup.
No force click, JSON salvage, fallback, or sixth wire-format generation was
introduced.

## Offline regression baseline

The full JVCLI suite runs 308 tests: 307 passed and one Python 3.10 TOML skip.
The 35 focused completion tests include 17 new test methods with parameterized
negative cases, atomic stale-plan reconciliation, bounded reasons/plan/commitment,
changed checkpoints, crash recovery, replay, legacy-state refusal and a second turn.

Central passes 648 core tests with one existing opt-in browser-matrix skip, plus
four current-client integration cases in a separate Python process. This split
is necessary because the historical pilot transport tests import their different
`jvcli` package into the process module cache. A combined invocation exposes that
existing import collision (four ModuleNotFoundError failures); the complete
collected tests pass when those two client versions are isolated. No tests are
omitted. The paired cases cover six-image/revisit, twenty-image, and six-image
stale-plan flows with actual scripted workspace operations and restart/replay.
Provider replacement coverage remains 91 tests, including replacement success and
double-malformed failure with no third attempt. The combined paired/provider/image/
file subset passes 180 cases. These subsets overlap the full-suite totals.
Unchanged provider suites pass 258 ChatGPT and 271 Gemini tests using disposable
test profiles and the existing browser binaries. No authenticated worker is started.

Real stock-engine checks pass 15 engine checks and nine parity checks. Existing
agent smoke passes two committed turns, eight logical responses, three workspace
tools and one evidence record. The new `scripts/completion_smoke.py` passes with
six actual view_image calls, six evidence records, a four-image maximum, one real
plan update, one shell artifact action, one completion review and three explicit
plan resolutions. Sixteen logical requests complete successfully. All inference
is scripted locally; workspace tools still execute through the unmodified engine.

Formatting, compilation and shell syntax checks are recorded in the audit.
Central retains its 69 existing Ruff findings; none are added or suppressed.
The full CLI lib/scripts/tests scope retains 124 existing findings with zero new;
changed CLI Python files pass Ruff with no findings. The audit compares full
relevant baseline/candidate lint inventories and includes exact build, integrity,
reproducibility, temporary offline installation and doctor results.

Initial harness failures (pilot/current-client import collision and an incomplete
scripted update_plan declaration) are documented, not counted as passing runs.
The declaration was corrected to match stock Codex. No provider change, JSON
repair, sandbox change or production retry was used.

Limits remain: three completion reviews, task requests 40/default and 500/max,
four active unique images, 17 MiB local structured body. Automatic raw-history
rollover is unavailable without upstream support. v1 task journals are preserved
and refused with a fresh-session diagnostic; they are not silently migrated.
Commitment validates model attestation and protocol state, not arbitrary domain
truth. See AGENT_COMPLETION.md and COMPLETION_AUDIT.md for authority and crash limits.
