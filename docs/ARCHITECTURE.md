# Architecture

```text
jvcli (Python launcher)
  | signs in to JV with username/password; keeps token in memory
  | starts authenticated 127.0.0.1 adapter
  | starts pinned local Codex engine with private CODEX_HOME
  v
Codex engine (unmodified Rust binary installed under runtime/)
  | Responses JSON over authenticated loopback HTTP
  v
JV adapter (Python)
  | neutral instructions + admitted tool schemas + bounded input history
  | multipart POST /v1/jobs; safe GET polling; no local tool execution
  v
JV API and server-selected model
  | answer text containing final text or structured tool envelope
  v
JV adapter
  | validates envelope and converts to Responses SSE events
  v
Codex engine
  | validates/runs local tools under requested sandbox
  | sends actual tool output with next model request
  v
Repeat until final answer or explicit failure/limit
```

## Modules

- `cli.py`: account settings, hidden password prompt, process environment, engine config, session locks, CLI and output/error handling.
- `transport.py`: independent synchronous stdlib API client, authentication, multipart uploads, polling, retries, file validation/downloads.
- `protocol.py`: prompt construction, admitted tools, context budget, strict output parsing, limited escape repair.
- `adapter.py`: authenticated loopback HTTP, SSE lifecycle/keepalive, in-flight lock, cancellation and loop limits.
- `safety.py`: exceptions, strict JSON, safe paths, private atomic file writes, terminal-control filtering and known-secret redaction.
- `scripts/manage.py`: per-user/portable installer, local engine setup, guarded uninstall, source updater with backups/rollback, and integrity verifier.

This is not a Rust SDK or a copy of Codex source. Existing JV Rust examples remain an independent protocol reference. Upstream technical identifiers are retained where required; the agent identity/instructions are JV CLI. Legal/provenance names remain in notices.

## Conversation choice

Coding mode uses **stateless replay to the JV job API**: each engine inference sends the bounded full conversation that the engine provides, without reusing a JV conversation ID. This avoids duplicating history when both the engine and server retain it. The local engine thread is persisted for interactive turns and `jvcli resume`.

Direct `jvcli ask --conversation-id` supports the JV API's native continuation independently. The current wrapper does not map one engine thread onto one long-lived server conversation. Consequently coding mode can create multiple JV conversations/jobs for one task; retention/billing is governed by the server.

## Supported compatibility subset

The adapter supports text messages, function calls, custom/freeform tool calls, their outputs, whole-history input, Responses JSON/SSE output, and `auto`/`none`/`required` tool choice. It is not a complete Responses implementation.

It rejects `previous_response_id`, background requests, image/audio input, and hosted tool types it cannot implement. No WebSocket transport, remote Responses state lookup or Responses compaction endpoint is provided. Custom tools are returned atomically in `output_item.done`.

Upstream JV jobs are polled; keepalive comments maintain the local stream while waiting. This is **not real model token streaming**. The adapter does not invent token usage/billing counts. It requests no artificial chain-of-thought disclosure.

## Context and reliability

The tool catalog is embedded in a text job, not passed as native JV API tool parameters. Instructions explicitly identify an external client executor: the model should return a protocol message and use the supplied client tool results instead of checking for client paths in the server's native environment.

The requested wire format is one fenced JSON code block. A live round-trip test found that unfenced code acquired Markdown-like damage, while a code block preserved it but returned a separate `JSON` language label. The parser accepts that exact label-plus-whole-block presentation as well as ordinary whole JSON/fences; it never extracts executable JSON from arbitrary surrounding prose. The precise server component responsible for the observed formatting was not inspected.

The API prompt is capped below 100 KiB. The adapter reserves bounded space for runtime instructions, complete tool definitions, newest user request and recent conversation. Oversized old history and whole tool definitions can be omitted with explicit markers. The adapter does not know the real server-assigned model's context window; catalog metadata is an adapter setting, not a hardware/model guarantee.

The adapter rejects malformed output before emitting tool calls. A confirmed completed job with invalid output can receive up to two correction jobs with the original task, catalog and actual tool results retained. Raw rejected text is not replayed; HTTP submission/poll failures are not resubmitted by this path. Repeated invalid output ends with an explicit failure and inspectable job ID. Exact observed generic provider error answers follow the same path; specific blockers/refusals remain final text. SSE keepalives continue during correction.

Custom multiline patches can use `input_lines`; literal newlines/tabs inside JSON strings can be encoded without changing their decoded value. Missing quotes, commas or truncated code are never invented. Native structured tool support at the server would reduce dependence on prompt adherence, but is not implemented here. Large repositories and long sessions require live evaluation.

## State layout

The normal application root is `~/.local/share/jv-cli`; portable mode uses the extracted repository. Account origin/username live in `.state/config.json` under that root. Each new session has `.state/runs/ID/` containing session metadata, engine home/history, neutral prompt, model catalog, tool home and temp files. It is bound to one username/origin/workspace. Random adapter keys remain memory-only and new ports/config are generated on resume.

The wrapper uses engine JSONL events, not the upstream full-screen TUI. Successful child exit alone is insufficient: a completed turn and nonempty assistant message are required. `turn.failed`, adapter failures and missing completion return failure.
