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
  | legacy default: bounded text envelope -> POST/GET /v1/jobs
  | structured opt-in: native messages/tools -> POST/GET /v1/responses
  v
JV API and server-selected model
  | legacy answer text, or one native message/function_call
  v
JV adapter
  | validates the complete result and converts it to local Responses SSE
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
- `structured.py`: native request adaptation, response/tool validation, durable idempotency and continuation state.
- `adapter.py`: authenticated loopback HTTP, SSE lifecycle/keepalive, in-flight lock, cancellation and loop limits.
- `safety.py`: exceptions, strict JSON, safe paths, private atomic file writes, terminal-control filtering and known-secret redaction.
- `scripts/manage.py`: per-user/portable installer, local engine setup, guarded uninstall, source updater with backups/rollback, and integrity verifier.

This is not a Rust SDK or a copy of Codex source. Existing JV Rust examples remain an independent protocol reference. Upstream technical identifiers are retained where required; the agent identity/instructions are JV CLI. Legal/provenance names remain in notices.

## Conversation choice

Legacy coding mode uses **stateless replay to the JV job API**: each engine inference sends the bounded full conversation that the engine provides, without reusing a JV conversation ID. The local engine thread is persisted for interactive turns and `jvcli resume`.

Opt-in structured mode adapts the first Codex request to the JV pilot's native message/tool request. A completed `function_call` is persisted before local publication. The following full-history Codex request is correlated with that exact call and reduced to a native `function_call_output` continuation using the prior opaque response ID. Instructions and the certified tool schema are resent because the remote protocol does not inherit them.

Direct `jvcli ask --conversation-id` supports the legacy JV API's native continuation independently. Legacy coding does not map one engine thread onto one long-lived server conversation and can create multiple JV conversations/jobs for one task. Structured coding uses response continuations only after client tool calls. Retention/billing is governed by the server.

## Supported compatibility subset

The legacy adapter supports text messages, function calls, custom/freeform tool calls, their outputs, whole-history input, Responses JSON/SSE output, and `auto`/`none`/`required` tool choice. It is not a complete Responses implementation.

Legacy mode rejects `previous_response_id`, background requests, image/audio input, and hosted tool types it cannot implement. Structured mode uses `previous_response_id` only for a validated tool continuation and currently certifies only `shell_command`. It filters other offered local tools from the remote declaration and rejects unsupported content/call output. Neither mode provides WebSockets or a compaction endpoint.

Upstream JV jobs are polled; keepalive comments maintain the local stream while waiting. This is **not real model token streaming**. The adapter does not invent token usage/billing counts. It requests no artificial chain-of-thought disclosure.

## Context and reliability

In legacy mode the tool catalog is embedded in a text job rather than passed as native JV API tool parameters. Its instructions identify an external client executor and request a protocol message. Structured mode sends the certified function schema natively and requests ordinary structured output.

The requested wire format is one fenced JSON code block. A live round-trip test found that unfenced code acquired Markdown-like damage, while a code block preserved it but returned a separate `JSON` language label. The parser accepts that exact label-plus-whole-block presentation as well as ordinary whole JSON/fences; it never extracts executable JSON from arbitrary surrounding prose. The precise server component responsible for the observed formatting was not inspected.

The API prompt is capped below 100 KiB. The adapter reserves bounded space for runtime instructions, complete tool definitions, newest user request and recent conversation. Oversized old history and whole tool definitions can be omitted with explicit markers. The adapter does not know the real server-assigned model's context window; catalog metadata is an adapter setting, not a hardware/model guarantee.

Both paths reject malformed output before emitting tool calls. Legacy mode can use up to two correction jobs after confirmed success. Structured mode never repairs model-facing text: a malformed native result is terminal for the client and client prompt repairs remain zero. Local SSE keepalives keep Codex waiting during asynchronous remote polling; they are not remote token streaming.

Legacy custom multiline patches can use `input_lines`; literal newlines/tabs inside JSON strings can be encoded without changing their decoded value. Missing quotes, commas or truncated code are never invented. Structured mode removes that text-format dependency but does not yet certify custom patch calls. Large repositories and long sessions require live evaluation.

## State layout

The normal application root is `~/.local/share/jv-cli`; portable mode uses the extracted repository. Account origin/username live in `.state/config.json` under that root. Each new session has `.state/runs/ID/` containing session metadata, engine home/history, neutral prompt, model catalog, tool home and temp files. Structured sessions additionally have `structured/state.json`, a private atomic journal of normalized bodies, idempotency keys, response IDs and tool-publication/continuation state. It is bound to one username/origin/workspace and transport mode. Random adapter keys remain memory-only and new ports/config are generated on resume.

The wrapper uses engine JSONL events, not the upstream full-screen TUI. Successful child exit alone is insufficient: a completed turn and nonempty assistant message are required. `turn.failed`, adapter failures and missing completion return failure.
