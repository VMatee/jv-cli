# Stdio bridge protocol 1

JV CLI **0.4.9** introduced this machine interface for Linux; **0.5.0** adds
official Windows trusted-host packages. Protocol version remains **1**.
Ordinary verification uses synthetic dependencies, never production accounts.

## Invocation and isolation

A trusted parent launches `jvcli bridge --stdio` with an explicit project `cwd`,
private stdin/stdout pipes, and a Desktop-specific `JVCLI_HOME`. The workspace is
validated by the existing CLI workspace checker before readiness. It is immutable
for this process. Start another process to change workspace. No engine, API login,
or session is started merely to emit readiness. `jvcli bridge --help` is local.

No request may specify a workspace, executable, shell, environment, attachment,
or image. Unknown fields are rejected, including terminal permission flags on
the bridge command line. Session policy is selected by `session.start`.
The existing CLI's default state location and all terminal commands are unchanged.

Windows dedicated workers explicitly select `jvcli bridge --stdio --execution-mode trusted-host`.
This immutable process option enables unrestricted tool filesystem/network access
and no approvals; it is never a fallback. Omitted mode preserves Linux defaults
and leaves Windows secure sessions unavailable. Mode status goes to stderr.
PTY/ConPTY, images, bridge transport alternatives and remote cancellation are deferred. Do not connect Desktop or a live account as part of ordinary tests.

## Wire rules

Both directions use UTF-8 NDJSON, one object per line. Blank input lines are
ignored. Output uses `ensure_ascii=False`; Thai remains readable. Stdout contains
only protocol frames, never raw engine JSON, prose, ANSI, exception details, or
HTTP bodies. Trusted-host startup diagnostics appear only on stderr; command-parser help
and invocation errors occur before the protocol starts. Consumers render text as
text, never HTML or executable content.

Each request has `type`, `request_id`, and optionally `protocol` (defaults to 1).
IDs match `[A-Za-z0-9_-]{1,100}`. Use distinct IDs for outstanding operations; the
bridge does not implement replay/deduplication. Acknowledgements/errors carry the
request ID. IDs are correlation labels, not authorization, turn identity, or
idempotency keys. Reusing one does not reuse or replace a turn. Turn stream events carry the generated `turn_id`; both the initial
and terminal turn frames also carry the originating request ID.

Duplicate keys, nonfinite numbers, invalid UTF-8, non-object JSON, invalid types,
unknown fields/types, and unsupported versions are rejected. Booleans must be
JSON booleans. A malformed request is recoverable; correlation is null when no
safe ID can be recovered. Prompts are rejected rather than truncated.

### Limits

| Boundary | Limit |
| --- | --- |
| Inbound line, excluding newline | 256 KiB (bounded 4096-byte read overshoot) |
| Prompt UTF-8 | 100 KiB, nonblank |
| Username / base URL / password UTF-8 | 256 / 2048 / 16384 bytes, nonblank |
| Request, session, turn identifier | 100 ASCII characters |
| Serialized outbound frame, including newline | 128 KiB |
| Queued outbound frames | 64; enqueue timeout 250 ms |
| Individual stdout write deadline | 5 seconds |
| Active turn / turn result queue | 1 / 1; no pending-turn queue |
| Engine input event | Existing 1 MiB limit; event queue 32 |
| Captured engine stderr | Existing last 100 chunks, each at most 8192 characters |
| Command / output / assistant text UTF-8 | 8192 / 16384 / 32768 bytes |
| Changed files / path / tool name | 50 / 1024 bytes / 256 bytes |

Normalized text fields are UTF-8 boundary-truncated and control/ANSI sanitized.
Large file lists are capped. These are display summaries, not complete logs.
An oversized inbound line yields `input_limit` once and is discarded through its
newline; processing can continue. Output overflow or sustained backpressure is
fatal and initiates local cleanup instead of accumulating unbounded memory.

## Lifecycle and requests

Logical states: READY → AUTHENTICATED → SESSION_READY ↔ TURN_RUNNING → STOPPING
→ CLOSED. The startup phase validates workspace. Authentication replacement is
allowed before a session, but session/account replacement is forbidden afterward.
Shutdown is accepted in every ready state. Invalid state transitions return errors.

Startup frame:

```json
{"type":"bridge.ready","protocol":1,"cli_version":"0.5.0","workspace":"/absolute/project","capabilities":{"auth":"stdio-memory","session":true,"resume":true,"cancel":"local","images":false,"thread_new":true}}
```

### Authentication

`auth.login` requires `username`, `base_url`, and `password` strings. Base URL
uses the existing strict validator (HTTPS or permitted loopback HTTP). Username
and URL reject control characters; username is trimmed. Success:

```json
{"type":"auth.succeeded","request_id":"login1"}
```

Password arrives **only through stdin**, is passed directly to the client login,
and is memory-only. It never enters argv, child environment, session metadata,
account config, or output. Local references are dropped after use. Python immutable
strings cannot be reliably zeroed; this is not a secure-erasure claim. Do not log
request bodies or pipe transcripts containing actual authentication requests.

Bridge login does not read or save terminal account defaults and does not use
`JV_API_PASSWORD`, getpass, or terminal auth persistence. It creates only the
existing private state directories as needed. Bearer tokens remain owned by the
client; Desktop never receives one. Replacement, failed login, and normal/fatal
cleanup attempt logout, dropping local token ownership even if revocation fails.
Authentication and session setup remain synchronous; another protocol request
cannot interrupt them. Bridge login adds a 30-second overall deadline around the
client call, and logout a 5-second deadline; the underlying socket idle timeouts
still apply. Deadline failures use the existing sanitized error categories.
Linux main-thread deadlines use SIGALRM, reserved by the bridge process.
Windows uses owned isolated helper processes, joins I/O and terminates expired
workers before state can be installed. Auth secrets travel on private pipes.
They do not change terminal client timeouts, endpoints, retries, or persistence.
Session setup is local: the shared engine version subprocess has a 10-second
timeout and locks are nonblocking. Ordinary filesystem operations still depend
on OS/filesystem responsiveness; no Python deadline guarantees recovery from an
uninterruptible kernel operation. An interrupted login may leave server-side
state unknown if no usable token was received.
The trusted local engine receives its existing local adapter key, not the JV
password or bearer token. Known token/adapter-key echoes are redacted from events.

### Session

`session.start` accepts optional `resume_session_id`, `read_only`, `allow_network`.
Absent policy fields use existing CLI defaults (workspace-write with network;
read-only defaults to no network), including when resuming. Read-only
plus explicit network enable is rejected. Windows trusted-host is selected only at process startup, never by a request.
In that mode, `read_only=true` or `allow_network=false` returns
`unsupported_capability` before session/engine creation. Pinned Windows restricted-token
network denial remains unsupported; no request silently enables networking.

```json
{"type":"session.started","request_id":"session1","session_id":"synthetic_session","workspace":"/absolute/project","sandbox":"workspace-write","network":false,"transport":"structured","thread_id":null}
```

`sandbox` is `read-only` or `workspace-write` for existing clients, or
`danger-full-access` when the parent explicitly opted into trusted-host; `network` is boolean; `transport`
reflects the existing selected mode, not a new bridge transport decision.
`thread_id` is null or an existing engine thread ID matching the bounded ASCII
identifier format and never starting with a hyphen. Engine thread events use
the same check before any ID can become a positional resume argument.
Corrupt saved thread metadata is rejected as `invalid_session`
rather than echoed as arbitrary JSON.

The shared `_session_runtime` context manager retains engine discovery/version
checks, workspace safety, private directories, session ID/path validation,
username/API-origin/workspace/transport resume binding, install/session locks,
policy configuration, metadata, and adapter lifecycle. `SessionRuntime.run_turn`
is used by both terminal and bridge frontends. Trusted-host metadata adds `execution_mode: "trusted-host"`; resume must explicitly
select the same mode. Existing Linux metadata is unchanged. Full prompts and bridge requests are not written to `session.json`.
Existing engine history behavior is unchanged and may retain conversation text
in the private session state; do not put credentials in prompts.

### Turn

`turn.start` requires `text`. It generates an opaque turn ID:

```json
{"type":"turn.started","request_id":"turn1","turn_id":"generated_id"}
```

The shared engine runner sends text over the engine's stdin with a native argument
vector, with one trailing newline appended (existing engine-runner behavior).
It neither invokes a shell nor spawns another `jvcli`. Existing public
`exec` positional prompts and `exec/resume --json` shapes remain unchanged.

Stable stream frames (all include `turn_id`):

| Type | Additional fields |
| --- | --- |
| `command.started` | `command`: string |
| `command.completed` | `command`, `output`: strings; `exit_code`: integer or null |
| `files.changed` | `changes`: array of `{path, kind}`; kind add/delete/update/unknown |
| `assistant.message` | `text`: string |
| `tool.started` | `name`: string |
| `turn.completed` | `request_id` |
| `turn.failed` | `request_id`, `code: engine_error`, static `message` |
| `turn.cancelled` | `request_id`, `local: true`, `remote_state: unknown` |

Known engine items are allowlisted and normalized; unknown events are ignored.
Raw engine errors are not forwarded. Completion/failure follows the shared runner's
validated outcome, not merely a raw `turn.completed` event. A second turn or
`thread.new` during execution/cleanup returns `turn_busy`. No turns are queued.

### Cancellation and new thread

`turn.cancel` requires the active `turn_id`. Acknowledgement:

```json
{"type":"turn.cancel.accepted","request_id":"cancel1","turn_id":"generated_id","local":true,"remote_state":"unknown"}
```

Cancellation signals the adapter and external engine cancellation event, stops
the owned Linux process group or Windows Job Object, and waits for local cleanup before allowing another
turn. Final `turn.cancelled` correlates to the original turn request. An already
submitted remote job **may continue**; no remote cancellation API is claimed.

`thread.new` has no extra fields and is allowed only while idle. It resets the
engine thread ID, preserving the session/history like terminal `/new`. Reply:
`{"type":"thread.started","request_id":"new1","thread_id":null}`.

### Shutdown, EOF, and exit status

`bridge.shutdown` has no extra fields. `bridge.stopping` acknowledges its request
ID, then local active work is cancelled and runtime/locks/client are closed.
A final turn cancellation frame can follow the stopping acknowledgement.
EOF follows the same cleanup without a stopping acknowledgement. Broken stdout
and output backpressure stop work; an acknowledgement may be impossible.
SIGINT/SIGTERM request cooperative local cleanup and produce exit 2. Signal
handlers only set flags; cleanup runs in the owner thread after any current
synchronous operation finishes or times out. Repeated signals do not interrupt
teardown. Terminal CLI signal behavior is unchanged. Bytes following a shutdown
request are not processed. Fragmented input does not block turn reaping or
stdout-failure detection.

Exit **0**: clean shutdown or EOF, including active-turn local cleanup. Recoverable
request errors do not change this status. Exit **2**: unsafe startup workspace,
unrecoverable bridge/transport failure, or cleanup failure. Parser invocation
errors also use 2 before the protocol starts.

The main thread owns authentication/session/lifecycle. One turn worker owns the
shared runner, with a size-one result queue; teardown joins it before closing the
session. One dedicated bounded writer serializes all stdout. Engine process wait,
readers, and writer have bounded waits. A turn worker that unexpectedly fails to
join within 15 seconds causes fatal process exit rather than concurrent session
teardown; restart is required, and no healthy continuation is attempted;
logout cannot be guaranteed in that catastrophic path. Forced process kill or OS
failure similarly cannot guarantee server-side token revocation. Normal fixture
cancellation, EOF, broken pipe, and shutdown verify cleanup and process termination.

## Errors

`request.error` has `request_id` (string or null), `code`, and a fixed sanitized
`message`. Codes: `invalid_request`, `unsupported_protocol`, `not_authenticated`,
`authentication_failed`, `session_not_started`, `session_busy`, `turn_busy`,
`invalid_session`, `workspace_error`, `engine_error`, `cancel_error`,
`internal_error`, `input_limit`, `unsupported_capability`. Session setup errors are deliberately grouped as
`invalid_session` to avoid leaking arbitrary engine/path/server exception text.
`engine_error` is also the terminal `turn.failed` code.

## Offline verification

`tests/fixtures/bridge_transcript.json` is an executable synthetic lifecycle
example replayed by `test_documented_transcript`. Its fake password is a leak-test
sentinel, not a credential. `bridge_runner.py` injects a fake client and fixture
engine internally while dispatching the real CLI parser. No production bypass
flag is exposed. Tests use isolated HOME/JVCLI_HOME, fake login/logout, a local
adapter, synthetic engine events, and no installed CLI/account state.

Tests cover stream purity, malformed/oversized requests, strict fields, Unicode,
multiple turns, resume binding/locks, busy rejection, cancellation, process-tree
cleanup, EOF, broken stdout, backpressure, and secret exclusion from output,
metadata, argv, and engine environment.
Windows trusted-host acceptance uses the public parser/stdio path, a loopback fake
JV service, and real pinned engine tools; see `scripts/windows_bridge_acceptance.py`. Existing terminal regression tests remain
mandatory. Live service acceptance requires separate authorization. Images and remote job
cancellation remain unsupported; ordinary package tests use synthetic services.
See [Milestone 3B review](BRIDGE_REVIEW.md) for adversarial findings and evidence.
