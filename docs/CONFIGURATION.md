# Configuration

## Account and service address

```bash
jvcli login --username your-user --base-url https://ai.openjvspace.com
jvcli auth status
jvcli logout
```

`login` verifies your account and saves your username and service address. Passwords and authentication tokens are not intentionally saved. Each process authenticates when needed. `auth status` shows configuration, not a live sign-in check. `logout` forgets saved account settings; exit other running sessions separately.

Saved configuration contains only these fields:

```json
{
  "base_url": "https://ai.openjvspace.com",
  "username": "your-user"
}
```

Do not add a password or token. Explicit login options take priority over environment settings, which take priority over saved defaults.

## Environment settings

| Setting | Default / purpose |
| --- | --- |
| `JV_API_BASE_URL` | Saved address or `https://ai.openjvspace.com` |
| `JV_API_USERNAME` | Saved username, otherwise an interactive prompt |
| `JV_API_PASSWORD` | Optional approved automation; normally use hidden input |
| `JVCLI_POLL_INTERVAL` | 2 seconds between status checks |
| `JVCLI_REQUEST_TIMEOUT` | 30 seconds per network operation |
| `JVCLI_WAIT_TIMEOUT` | 300 seconds per request's status wait |
| `JVCLI_TURN_TIMEOUT` | 3600 seconds per coding turn |
| `JVCLI_MAX_REQUESTS` | 40 requests per turn; valid range 1–500 |
| `JVCLI_AGENT_API` | Set to `1` for optional image-assisted task mode |

Time values must be finite and positive. For example, allow a ten-minute response wait:

```bash
JVCLI_WAIT_TIMEOUT=600 jvcli
```

A timeout stops local waiting; it does not guarantee remote work was cancelled. Check the known request/session before submitting the same task again.

## Permissions

Normal sessions can edit the selected workspace and use network-enabled project tools. Use `--read-only` for inspection or `--no-network` to disable project-tool networking. The JV service connection still requires internet access.

Flags work before or after `exec`/`resume`; a subcommand flag overrides a preceding flag. `--read-only --allow-network` is invalid. `/permissions` shows the current policy without changing it; restart with the desired flags to change policy.

## Images and saved sessions

With `JVCLI_AGENT_API=1`, `exec` and `resume` accept up to four `--image PATH` options. Use PNG, JPEG, or WebP files inside the selected workspace, without symlinks. Account capabilities and service size limits also apply.

Resume with the same workspace, account, service address, and optional mode. Session files can contain project content and images. Keep application state and backups private and do not edit session files manually.

## Service connections

Use an HTTPS origin without embedded credentials, query strings, fragments, or `/v1/...` paths. Loopback HTTP is supported for local testing only. TLS verification remains enabled. Configure trusted certificates for private deployments rather than disabling checks.
