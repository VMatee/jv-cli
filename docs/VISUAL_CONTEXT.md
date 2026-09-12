# Bounded visual context — deployed architecture

This architecture originated as the independently audited 0.4.1 candidate and is
now deployed as part of the canonical 0.4.3 structured-agent stack. Scenario 01
received live visual-grading acceptance on 2026-09-12. Historical offline evidence
below retains its original scope. Public contract `52be898` remains a historical
interface baseline, and the former Server WIP reference records the proposal-stage
design provenance.

## Canonical observations and active bytes

`MAX_ACTIVE_CONTEXT_IMAGES = 4` is not a total task image count. Central keeps the
normalized canonical transcript and each owner-scoped response's immutable input
record. An image observation retains its original call/result identity and order,
response/predecessor relationship, declared path in its associated client call
(where originally supplied), MIME, size and SHA-256. Local paths are not opened
by Central. Initial images need not disclose a local path. Neither canonical
requests nor past jobs are rewritten during eviction.

Central selects the four most recently observed distinct image content identities
(kind, MIME, SHA-256). A repeated observation refreshes that identity's recency.
Identical images may share one active binary, but their call/result events remain
separate. Selection depends only on canonical observation order, so an exact
retry or restart produces the same set. Upload ordering keeps current artifacts
first and preserves the predecessor's retained order. Prior file artifacts remain
pinned; generic file eviction is deliberately not implemented.

For distinct images 1 through 6, the active sets are 1; 1,2; 1,2,3; 1,2,3,4;
2,3,4,5; 3,4,5,6. Providers receive only selected, integrity-checked artifact bytes.
Admission examines at most the new request plus the preceding bounded active
set. No cumulative binary list is fetched from all prior jobs. Each job retains
at most the bounded active attachment package; historical metadata and source
job records still grow within explicit task/storage budgets.

## Reference-only compiled history

Only the model-facing copy changes. An inactive `input_image` becomes an internal
`input_image_reference`, with the original artifact metadata, `visual_content:
inactive` and a factual reinspection notice. Its containing message/tool result,
call ID and chronology remain intact. Its descriptor is not an image description.
There is no OCR, captioning, inferred visual summary or claim of remembered detail.
The compiled attachment map includes only active binaries. Normal text/image
requests without eviction compile byte-identically to the accepted baseline;
provider implementations and their normal prompts are untouched.

If details of an inactive image matter, the model must request another local
`view_image` observation using its earlier call's path. Initial images without a
known path require the user to supply the image again. A new observation uses a
new call ID and validated returned bytes. If the file has changed, its new content
identity describes the new observation; the old observation is never rewritten.
The unchanged client executor performs local tool reads. Central cannot reopen
workspace paths. The paired offline harness additionally exercises the existing
workspace/symlink-safe snapshot reader on every read and rejects a symlink on
reopen; the real-engine check exercises actual repeated native `view_image` calls.
These checks do not add a stronger filesystem sandbox to the pinned engine.

## Client replay and restart

Pinned Codex replays full local input. JVCLI validates every image and each result
array, then checks saved call class, ID, exact arguments/path and result digest.
Changed historical results fail before new submission. The historical image count
is no longer compared to the active window. Normal continuations still transmit
only the new result with the predecessor and a durable idempotency key. Exact
completed retries use the journal; ambiguous submissions retain the existing
same-key reconciliation and unresolved-side-effect protections.

Private bounded client request journals retain exact bodies needed for ambiguous
submission recovery. Image bytes are not printed or added to diagnostic logs.
Server canonical metadata uses descriptors, never raw base64. This change does
not migrate old sessions or delete any failed-session evidence.

## Independent bounds

| Resource | Bound |
| --- | --- |
| New request or individual image-result array | 4 images |
| Active provider images | 4 distinct image identities |
| Combined active images/files | 6 attachments |
| Per image / current active image bytes | 5 MiB / 12 MiB |
| Existing file-only / mixed artifact bytes | 20 MiB / 24 MiB (unchanged) |
| Image axes / pixels | 8192 per axis / 16,000,000 |
| Local and remote structured HTTP body | 17 MiB |
| Normalized remote request metadata | 64 KiB |
| JVCLI model requests per turn | 40 default; `JVCLI_MAX_REQUESTS`, 1–500 |
| JVCLI durable session | 500 rounds and 64 MiB journal |
| Central conversation rounds | 40 default; `COMBINED_AGENT_MAX_ROUNDS`, 1–500 |
| Time | Existing five-minute job and one-hour client-turn defaults |
| Repeated identical client actions | Existing fourth-repeat rejection |
| Fresh JV-WIRE wire-format generations | 5 maximum: generation 1 plus corrections 2-5; no generation 6 |
| Frozen legacy provider attempts | Existing maximum 2; no attempt 3 |

Central freezes the configured round budget in the first canonical request;
resume and later configuration changes cannot raise that conversation's budget.
Exhaustion fails before registration/dispatch with `Structured task round budget
exhausted`. Existing conversations without that field adopt the configured
budget at their next accepted continuation. JVCLI's session cap and per-turn
model budget remain independent and are not reset by visual eviction. These
existing limits permit the 20-observation test without arbitrary enlargement.

Count-based eviction does not silently relax byte or combined limits: if the
selected four images exceed 12 MiB, or pinned files plus the active set exceed
six attachments, admission still fails. Staged-file validation, artifact expiry,
canonical integrity, MIME/full decode and provider capability checks remain intact.

Pinned Codex's full local replay can still hit the existing 17 MiB incoming
request ceiling before the task-round budget for large images. Private journal
size and Server text/context size can also stop a task earlier. This architecture
bounds provider binary payloads, not unlimited engine history, metadata, disk,
time or inference. No cumulative image-count ceiling is used as a task budget.

## Historical offline acceptance and later live acceptance

Tests cover 20 distinct observations, a revisit, exact six-page order, bounded
active binaries, metadata-only eviction, immutable old records, restart/retry,
tampered historical bytes/path/call IDs, task exhaustion and existing safety.
The paired test connects current JVCLI directly to a disposable Flask test app:
no production API or provider runs. Run it separately from Central's legacy pilot
client tests because that old fixture uses the same Python package name:

```sh
PYTHONPATH=. .venv/bin/python -m pytest -q tests --ignore=tests/test_visual_context_client.py
JVCLI_SOURCE=/path/to/jvcli PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_visual_context_client.py
```

All application test homes/state are disposable. The audit records exact results,
source hashes, baseline lint limitations, and the unchanged production checks.
Those checks record the original offline acceptance stage and remain historical
audit evidence. The architecture was subsequently deployed and Scenario 01 was
live-accepted on 2026-09-12 with `SCENARIO_RC=0`. The six-page scanned-PDF
workflow used bounded visual observations without OCR, preserved the source PDFs,
and retained an ambiguous answer as `REVIEW_REQUIRED` rather than guessing it.
Repository commit, tag and GitHub Release publication remain separate
release-management gates.
