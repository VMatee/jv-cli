#!/usr/bin/env python3
"""Offline pinned-engine feasibility probe for native Windows and Linux.

Run with an explicit engine binary. This does not log in, install, or contact JV.
Only synthetic model replies from the in-process loopback adapter are used.
This is an engineering probe, not the JV CLI Windows implementation.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "lib"))

from jvcli.adapter import AdapterRuntime  # noqa: E402
from jvcli.protocol import BASE_AGENT_INSTRUCTIONS  # noqa: E402
from jvcli.safety import JvError  # noqa: E402
from jvcli.transport import JvClientConfig  # noqa: E402

ENGINE_VERSION = "0.149.1"
FINAL_TEXT = "WINDOWS_ENGINE_PROBE_OK"


class SyntheticClient:
    _token = None
    base_url = "http://127.0.0.1"

    def __init__(self, command: str, marker: str):
        self.command = command
        self.marker = marker
        self.config = JvClientConfig(request_timeout=3, wait_timeout=10, poll_interval=0.01)
        self.requests = 0
        self.pending = {}

    def submit_job(self, prompt: str) -> dict:
        self.requests += 1
        if self.requests == 1:
            answer = {"type": "tool_call", "name": "shell_command", "arguments": {"command": self.command}}
        elif (self.requests == 2 and "[tool result " in prompt
              and self.marker in prompt.rsplit("[tool result ", 1)[-1]):
            answer = {"type": "final", "text": FINAL_TEXT}
        else:
            raise JvError("Synthetic continuation was missing or a duplicate model request occurred")
        job_id = f"synthetic_probe_{self.requests}"
        self.pending[job_id] = json.dumps(answer)
        return {"id": job_id, "conversation_id": f"synthetic_conversation_{self.requests}", "status": "queued"}

    def wait_for_job(self, job_id: str, **kwargs) -> dict:
        return {
            "id": job_id,
            "conversation_id": kwargs.get("conversation_id"),
            "status": "succeeded",
            "answer": self.pending[job_id],
            "response": {"files": []},
        }


def toml(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(toml(key) + " = " + toml(item) for key, item in value.items()) + " }"
    raise TypeError("Unsupported probe configuration")


def model_catalog() -> dict:
    # Mirrors the pinned engine's local model contract in cli._model_catalog.
    return {"models": [{
        "slug": "jv-local", "display_name": "JV Local", "description": "Synthetic probe",
        "default_reasoning_level": None, "supported_reasoning_levels": [],
        "shell_type": "shell_command", "visibility": "list", "supported_in_api": True,
        "priority": 0, "availability_nux": None, "upgrade": None,
        "support_verbosity": False, "default_verbosity": None,
        "apply_patch_tool_type": "freeform", "truncation_policy": {"mode": "tokens", "limit": 10000},
        "context_window": 32768, "experimental_supported_tools": [],
        "tool_mode": "direct", "base_instructions": BASE_AGENT_INSTRUCTIONS,
    }]}


def config_for(folder: Path, port: int, *, read_only: bool = False) -> tuple[Path, list[str]]:
    engine_home = folder / "engine"
    engine_home.mkdir()
    tool_home = folder / "tool-home"
    tool_home.mkdir()
    temporary = folder / "tmp"
    temporary.mkdir()
    catalog = folder / "model_catalog.json"
    catalog.write_text(json.dumps(model_catalog(), ensure_ascii=False), encoding="utf-8")
    instructions = folder / "instructions.md"
    instructions.write_text(BASE_AGENT_INSTRUCTIONS, encoding="utf-8")
    config = {
        "model": "jv-local", "model_provider": "jv",
        "model_catalog_json": str(catalog), "model_instructions_file": str(instructions),
        "approval_policy": "never", "sandbox_mode": "read-only" if read_only else "workspace-write",
        "hide_agent_reasoning": True, "web_search": "disabled",
        "check_for_update_on_startup": False,
        "features": {"code_mode": False, "code_mode_only": False, "shell_tool": True,
                     "unified_exec": False, "apply_patch_freeform": True},
        "analytics": {"enabled": False},
        "model_providers": {"jv": {"name": "Synthetic JV", "base_url": f"http://127.0.0.1:{port}/v1",
                                   "wire_api": "responses", "requires_openai_auth": False,
                                   "supports_websockets": False, "env_key": "JVCLI_ADAPTER_KEY",
                                   "request_max_retries": 0, "stream_max_retries": 0,
                                   "stream_idle_timeout_ms": 120000}},
        "sandbox_workspace_write": {"network_access": False, "exclude_slash_tmp": True,
                                    "exclude_tmpdir_env_var": False,
                                    "writable_roots": [str(tool_home)]},
        "shell_environment_policy": {"inherit": "core", "ignore_default_excludes": False,
                                     "exclude": ["JVCLI_ADAPTER_KEY", "JV_API_PASSWORD", "JV_API_USERNAME"],
                                     "set": {"JVCLI_ADAPTER_KEY": "", "HOME": str(tool_home),
                                             "TMPDIR": str(temporary),
                                             "XDG_CACHE_HOME": str(tool_home / ".cache"),
                                             "PIP_REQUIRE_VIRTUALENV": "true",
                                             "PIP_DISABLE_PIP_VERSION_CHECK": "1"}},
    }
    (engine_home / "config.toml").write_text(
        "\n".join(f"{key} = {toml(value)}" for key, value in config.items()) + "\n",
        encoding="utf-8",
    )
    overrides = [part for key, value in config.items() for part in ("-c", f"{key}={toml(value)}")]
    return engine_home, overrides


def isolated_env(folder: Path, engine_home: Path, key: str) -> dict[str, str]:
    allowed = ("PATH", "SystemRoot", "WINDIR", "ComSpec", "PATHEXT", "NUMBER_OF_PROCESSORS",
               "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ")
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env.update({"CODEX_HOME": str(engine_home), "HOME": str(folder / "tool-home"),
                "USERPROFILE": str(folder / "tool-home"),
                "APPDATA": str(folder / "tool-home" / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(folder / "tool-home" / "AppData" / "Local"),
                "TMP": str(folder / "tmp"), "TEMP": str(folder / "tmp"),
                "TMPDIR": str(folder / "tmp"), "JVCLI_ADAPTER_KEY": key,
                "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"})
    return env


def engine_round(engine: Path, folder: Path, workspace: Path, command: str,
                 marker: str = "", *, read_only: bool = False,
                 successful_command: bool = False) -> dict:
    folder.mkdir()
    client = SyntheticClient(command, marker)
    runtime = AdapterRuntime(client, heartbeat=0.5)
    try:
        port = runtime.start()
        runtime.begin_turn()
        engine_home, overrides = config_for(folder, port, read_only=read_only)
        env = isolated_env(folder, engine_home, runtime.key)
        version = subprocess.run([str(engine), "--version"], cwd=workspace, env=env,
                                 capture_output=True, text=True, timeout=15, check=True)
        found = re.search(r"\b\d+\.\d+\.\d+", version.stdout)
        if not found or found.group() != ENGINE_VERSION:
            raise JvError("Engine version does not match the 0.149.1 pin")
        args = [str(engine), *overrides, "exec", "--json", "--skip-git-repo-check",
                "--ignore-rules", "--color", "never", "-"]
        process = subprocess.Popen(args, cwd=workspace, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", start_new_session=os.name != "nt")
        try:
            stdout, _ = process.communicate("Read probe.txt with the shell tool once, then report success.\n",
                                            timeout=120)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
            raise JvError("Pinned engine timed out during the synthetic probe") from None
        events = []
        for line in stdout.splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    raise JvError("Engine emitted an invalid JSON event") from None
        execution = [e for e in events if e.get("type") == "item.completed"
                     and e.get("item", {}).get("type") == "command_execution"]
        final = [e for e in events if e.get("type") == "item.completed"
                 and e.get("item", {}).get("type") == "agent_message"
                 and e["item"].get("text", "").strip() == FINAL_TEXT]
        completed = any(e.get("type") == "turn.completed" for e in events)
        if marker == "KEY_SAFE" and any(
            "KEY_UNSAFE" in (item["item"].get("aggregated_output") or "")
            for item in execution
        ):
            raise JvError("Adapter key had a nonempty value in the shell tool environment")
        if (process.returncode != 0 or client.requests != 2 or len(execution) != 1
                or len(final) != 1 or not completed):
            raise JvError(
                "Synthetic engine gate failed: "
                f"exit_nonzero={process.returncode != 0}, "
                f"model_requests={client.requests}, tool_executions={len(execution)}, "
                f"final_answers={len(final)}, turn_completed={completed}"
            )
        if successful_command and execution[0]["item"].get("exit_code") not in (0, "0"):
            raise JvError("Synthetic shell command did not succeed")
        if marker and marker not in (execution[0]["item"].get("aggregated_output") or ""):
            raise JvError("Synthetic tool output did not contain the required marker")
        return {"model_requests": client.requests, "tool_executions": len(execution)}
    finally:
        runtime.close()


def shell_write(path: Path) -> str:
    if os.name == "nt":
        escaped = str(path).replace("'", "''")
        return ('pwsh -NoLogo -NoProfile -NonInteractive -Command '
                f'"Set-Content -LiteralPath \'{escaped}\' -Value changed"')
    return "printf changed > " + shlex.quote(str(path))


def run_probe(engine: Path) -> dict:
    if not engine.is_file():
        raise JvError("The explicit pinned engine binary was not found")
    if os.name == "nt" and engine.suffix.lower() != ".exe":
        raise JvError("Pass the native codex.exe binary, not a .cmd launcher")
    with tempfile.TemporaryDirectory(prefix="jvcli-engine-feasibility-") as base:
        folder = Path(base)
        workspace = folder / "workspace"
        workspace.mkdir()
        marker = "SYNTHETIC_PROBE_FILE_OK"
        (workspace / "probe.txt").write_text(marker, encoding="utf-8")
        read_command = (
            'pwsh -NoLogo -NoProfile -NonInteractive -Command "Get-Content -LiteralPath probe.txt -Raw"'
            if os.name == "nt" else "cat probe.txt"
        )
        engine_round(engine, folder / "read", workspace, read_command, marker,
                     successful_command=True)
        allowed = workspace / "allowed.txt"
        engine_round(engine, folder / "allowed", workspace, shell_write(allowed),
                     successful_command=True)
        if allowed.read_text(encoding="utf-8").strip() != "changed":
            raise JvError("Workspace-write control did not create its expected file")
        outside = folder / "protected.txt"
        outside.write_text("unchanged", encoding="utf-8")
        engine_round(engine, folder / "outside", workspace, shell_write(outside))
        if outside.read_text(encoding="utf-8") != "unchanged":
            raise JvError("Sandbox allowed a write outside the workspace")
        readonly = workspace / "readonly-must-not-exist.txt"
        engine_round(engine, folder / "readonly", workspace, shell_write(readonly), read_only=True)
        if readonly.exists():
            raise JvError("Read-only sandbox allowed a workspace write")

        hits = []

        class NetworkTarget(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                hits.append(True)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        server = ThreadingHTTPServer(("127.0.0.1", 0), NetworkTarget)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            target = f"http://127.0.0.1:{server.server_address[1]}/"
            if os.name == "nt":
                control = ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                           f"Invoke-WebRequest -Uri {target} -TimeoutSec 2 | Out-Null"]
                subprocess.run(control, cwd=workspace, capture_output=True, timeout=10,
                               check=True)
            elif urllib.request.urlopen(target, timeout=2).read() != b"ok":
                raise JvError("Loopback network control failed")
            if len(hits) != 1:
                raise JvError("Loopback network control did not reach the target once")
            hits.clear()
            network_command = (
                'pwsh -NoLogo -NoProfile -NonInteractive -Command '
                f'"try {{ Invoke-WebRequest -Uri {target} -TimeoutSec 2 | Out-Null }} catch {{ }}"'
                if os.name == "nt" else
                'python3 -c ' + shlex.quote(
                    f"import urllib.request; urllib.request.urlopen({target!r}, timeout=2).read()")
            )
            engine_round(engine, folder / "network", workspace, network_command)
            if hits:
                raise JvError("Sandbox allowed tool network access")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

        key_command = (
            'pwsh -NoLogo -NoProfile -NonInteractive -Command '
            '"if ([string]::IsNullOrEmpty($env:JVCLI_ADAPTER_KEY)) '
            '{ Write-Output KEY_SAFE } else { Write-Output KEY_UNSAFE }"'
            if os.name == "nt" else
            'python3 -c ' + shlex.quote(
                "import os; print('KEY_UNSAFE' if os.environ.get('JVCLI_ADAPTER_KEY') else 'KEY_SAFE')")
        )
        engine_round(engine, folder / "key", workspace, key_command, "KEY_SAFE",
                     successful_command=True)

        return {"result": "PASS", "engine_version": ENGINE_VERSION,
                "cases": 6, "synthetic_model_requests": 12, "shell_executions": 6,
                "continuation": True, "final_answer": True,
                "workspace_write_control": True, "adapter_key_value_hidden_from_tool": True,
                "sandbox_outside_write_denied": True, "sandbox_read_only_write_denied": True,
                "sandbox_network_denied": True, "real_inference_submitted": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path,
                        help="Absolute path to pinned native Codex binary; no install is performed")
    args = parser.parse_args()
    try:
        print(json.dumps(run_probe(args.engine.absolute()), sort_keys=True))
        return 0
    except (JvError, OSError, subprocess.SubprocessError) as exc:
        # Diagnostics are content-free; never print child environment or responses.
        result = {"result": "FAIL", "classification": type(exc).__name__,
                  "real_inference_submitted": False}
        if isinstance(exc, JvError) and str(exc).startswith((
            "Adapter key had a nonempty value", "Synthetic engine gate failed:",
            "Sandbox allowed", "Read-only sandbox allowed",
            "Workspace-write control", "Synthetic shell command", "Pinned engine timed out",
            "Engine version does not match", "Loopback network control",
        )):
            result["gate"] = str(exc)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
