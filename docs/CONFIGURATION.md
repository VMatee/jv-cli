# Configuration

`jvcli login` saves `.state/config.json` containing only:

```json
{
  "base_url": "https://ai.openjvspace.com",
  "username": "your-user"
}
```

Unknown config fields fail validation. Never add a password or token. Explicit login options override environment/account settings; environment values override saved defaults.

```bash
jvcli login --username your-user --base-url https://your-jv-server.example
jvcli auth status
jvcli logout
```

`login` verifies and revokes its temporary token immediately; it does not create a permanently signed-in shell. `logout` forgets the stored username/origin; other running sessions must exit separately to revoke their tokens. `auth status` reports configuration, not a live authentication check.

## Environment settings

| Variable | Default / meaning |
| --- | --- |
| `JV_API_BASE_URL` | Saved origin or https://ai.openjvspace.com |
| `JV_API_USERNAME` | Saved username, otherwise prompt on a terminal |
| `JV_API_PASSWORD` | Automation only; normally use hidden input |
| `JVCLI_HOME` | `INSTALL_ROOT/.state`; overriding changes where state is owned |
| `JVCLI_CODEX_BIN` | Optional explicit executable path; must report pinned version |
| `JVCLI_POLL_INTERVAL` | 2 seconds |
| `JVCLI_REQUEST_TIMEOUT` | 30 seconds per blocking network operation |
| `JVCLI_WAIT_TIMEOUT` | 300 seconds (5 minutes) per model job's polling deadline |
| `JVCLI_TURN_TIMEOUT` | 3600 seconds for a coding turn |
| `JVCLI_MAX_REQUESTS` | 40 model requests per turn, maximum 500 |
| `JVCLI_AGENT_API` | `0`; set exactly `1` to opt into structured `/v1/responses` |

Time values must be finite and positive. Request socket timeouts are not a guarantee against every slow-response/OS scheduling condition; cancellation is best-effort for an already-blocked network operation.

To change the per-call wait later, for example to ten minutes:

```bash
JVCLI_WAIT_TIMEOUT=600 jvcli --allow-network
```

The engine SSE deadline accommodates the legacy initial job plus up to two correction jobs and submission overhead. Structured mode uses the same conservative local stream bound but performs no prompt-repair jobs. The whole coding turn still has its independent `JVCLI_TURN_TIMEOUT`. A timeout stops local waiting, not the remote job/response. Server-side authentication failures require operator investigation; extra waiting cannot authenticate a provider.

HTTPS is required except loopback HTTP. Base origins must not contain embedded credentials, query, fragment or API paths. `/v1/...` routes are added by the client. Ambient proxies are disabled. TLS certificate verification is not disabled; private deployments must arrange trusted certificates separately.

## Defaults and limits

- Pinned engine: 0.149.1; model alias: `jv-local`.
- Legacy `/v1/jobs` remains the coding default. `JVCLI_AGENT_API=1` selects the structured pilot and must match when resuming a saved session.
- Default: workspace-write with tool networking, no elevation approval, no automatic sandbox bypass.
- `--read-only` requests denial of tool writes and disables tool networking.
- `--no-network` disables tool networking in write mode; JV API traffic still requires networking.
- `--allow-network` explicitly enables tool networking only for workspace-write. It does not grant sudo or system-wide file access. Network flags work before or after `exec`/`resume`; a subcommand flag overrides a flag before the subcommand.
- Max incoming adapter JSON: 8 MiB in legacy mode; 17 MiB in structured mode, with separate 64 KiB structured metadata limits.
- JV text submission: 100 KiB; coding prompt budget: 96 KiB.
- Uploads: at most 10 files, 25 MiB each, 100 MiB combined; regular non-symlink files.
- Downloads: at most 10 files, 25 MiB each, 100 MiB combined; exact declared size, no overwrite.
- Model output: at most 8 tool calls in an envelope. A fourth identical action in a turn stops the loop.
- Invalid completed model responses: at most two correction jobs per response, also counted against `JVCLI_MAX_REQUESTS` and the turn timeout. Progress is shown; session metadata records `model_requests` and `response_repairs`. Additional jobs can consume service quota.
- ID validation: ASCII letters, digits, hyphens and underscores. Other opaque-ID formats are unsupported.
- Structured mode admits `shell_command` and `update_plan`, plus initial user-message PNG/JPEG/WebP images. The certified custom apply_patch and image-only view_image result arrays are supported. Other custom tools, hosted/MCP tools, audio, remote streaming and parallel calls remain unsupported.
- Each structured logical round stores its normalized body, idempotency key, response ID and publication state privately under the session directory. State is bounded and atomically replaced.

Some limits are deliberately conservative. The server can enforce stricter limits. The tool argument checker covers common types/required fields, not every JSON Schema keyword.

## Generated engine configuration

Each session gets independent `.state/runs/ID/engine/config.toml`, catalog and instructions. They are regenerated on launch/resume; edit the wrapper only after reviewing tests rather than manually changing generated files. Adapter auth uses `env_key`; no token is written into TOML.

The tool HOME/TMPDIR/cache are private local paths. `PIP_REQUIRE_VIRTUALENV=true` discourages global pip installation. The engine environment is restricted rather than a copy of the invoking shell: custom PATH-based tooling may work, but arbitrary application secrets or SDK environment settings are not propagated automatically.

## Structured initial images

With `JVCLI_AGENT_API=1`, `exec` and `resume` accept repeated `--image PATH` options (up to four PNG/JPEG/WebP images). Paths must be beneath the workspace with no symlinks. Private snapshots and durable image request bodies remain in session state. The structured journal is bounded to 64 MiB; non-image metadata remains bounded to 64 KiB. `auto` and `high` image detail are supported; remote URLs and original detail are rejected. See [the parity audit](CODEX_PARITY.md) for certified wire forms and live acceptance status.
