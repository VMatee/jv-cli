import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class E2EJvHandler(BaseHTTPRequestHandler):
    job_count = 0
    jobs = {}
    saw_logout = False
    submitted = []
    answer_sequence = None

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        cls = type(self)
        if self.path == "/v1/auth/login":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length))
            if data.get("username") != "user" or data.get("password") != "pass":
                self.send_response(401)
                self.end_headers()
                return
            raw = json.dumps({"access_token": "e2e-token"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == "/v1/auth/logout":
            cls.saw_logout = True
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/v1/jobs":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", "ignore")
            cls.submitted.append(body)
            cls.job_count += 1
            job_id = f"job_{cls.job_count}"
            conv_id = f"conv_{cls.job_count}"
            if cls.answer_sequence is not None:
                answer = cls.answer_sequence[min(cls.job_count - 1, len(cls.answer_sequence) - 1)]
            elif cls.job_count == 1:
                answer = r'{"type":"tool\_call","name":"shell\_command","arguments":{"command":"pwd","timeout\_ms":10000}}'
            else:
                answer = '{"type":"final","text":"E2E done"}'
            cls.jobs[job_id] = (conv_id, answer)
            payload = {
                "id": job_id,
                "conversation_id": conv_id,
                "status": "queued",
                "result_ready": False,
                "response": {"files": []},
            }
            raw = json.dumps(payload).encode()
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        cls = type(self)
        if self.path.startswith("/v1/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            if job_id not in cls.jobs:
                self.send_response(404)
                self.end_headers()
                return
            conv_id, answer = cls.jobs[job_id]
            payload = {
                "id": job_id,
                "conversation_id": conv_id,
                "status": "succeeded",
                "result_ready": True,
                "answer": answer,
                "response": {"files": []},
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_response(404)
        self.end_headers()


FAKE_ENGINE = r'''#!/usr/bin/env python3
import json, os, re, sys, urllib.request
from pathlib import Path

if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print("codex-cli 0.149.1")
    raise SystemExit(0)

config = (Path(os.environ["CODEX_HOME"]) / "config.toml").read_text()
match = re.search(r'"base_url" = "(http://127\.0\.0\.1:\d+/v1)"', config)
if not match:
    print("missing provider url", file=sys.stderr)
    raise SystemExit(2)
base = match.group(1)
catalog_match = re.search(r'model_catalog_json = "([^"]+)"', config)
if not catalog_match:
    print("missing model catalog", file=sys.stderr)
    raise SystemExit(2)
catalog = json.loads(Path(catalog_match.group(1)).read_text())
model = catalog["models"][0]
if model.get("slug") != "jv-local" or model.get("shell_type") != "shell_command" or model.get("tool_mode") != "direct":
    print("invalid model catalog", file=sys.stderr)
    raise SystemExit(2)
if '"code_mode" = false' not in config or '"shell_tool" = true' not in config:
    print("invalid tool feature config", file=sys.stderr)
    raise SystemExit(2)

def request(payload):
    req = urllib.request.Request(base + "/responses", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + os.environ["JVCLI_ADAPTER_KEY"]}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        text = r.read().decode()
    events = []
    for block in text.split("\n\n"):
        if not block.startswith("data: "):
            continue
        value = block[6:].strip()
        if value == "[DONE]":
            continue
        events.append(json.loads(value))
    failure = next((e for e in events if e.get("type") == "error"), None)
    if failure:
        message = failure.get("message", "adapter failed")
        print(json.dumps({"type":"error","message":message}), flush=True)
        print(json.dumps({"type":"turn.failed","error":{"message":message}}), flush=True)
        raise SystemExit(1)
    return events

print(json.dumps({"type":"thread.started","thread_id":"thread_e2e"}), flush=True)
print(json.dumps({"type":"turn.started"}), flush=True)
tools = [{"type":"function","name":"shell_command","description":"Run shell command","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}]
items = [{"type":"message","role":"user","content":[{"type":"input_text","text":"test task"}]}]
events = request({"model":"jv-local","instructions":"You are JV CLI","input":items,"tools":tools,"stream":True})
call = next(e["item"] for e in events if e.get("type") == "response.output_item.done" and e.get("item",{}).get("type") == "function_call")
if call.get("name") != "shell_command":
    print("tool name was not normalized", file=sys.stderr)
    raise SystemExit(3)
call_args = json.loads(call.get("arguments", "{}"))
if call_args.get("timeout_ms") != 10000:
    print("tool argument keys were not normalized", file=sys.stderr)
    raise SystemExit(3)
print(json.dumps({"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"pwd"}}), flush=True)
print(json.dumps({"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"pwd","exit_code":0,"aggregated_output":"/tmp\n"}}), flush=True)
items.extend([call, {"type":"function_call_output","call_id":call["call_id"],"output":"/tmp\n"}])
events = request({"model":"jv-local","instructions":"You are JV CLI","input":items,"tools":tools,"stream":True})
msg = next(e["item"] for e in events if e.get("type") == "response.output_item.done" and e.get("item",{}).get("type") == "message")
text = msg["content"][0]["text"]
print(json.dumps({"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":text}}), flush=True)
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":4}}), flush=True)
'''


class CliEndToEndTests(unittest.TestCase):
    def recovery_case(self, answers, *, success):
        class Handler(E2EJvHandler):
            job_count, jobs, submitted, saw_logout = 0, {}, [], False
            answer_sequence = answers
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                home, workspace = root / "home", root / "workspace"
                home.mkdir()
                workspace.mkdir()
                fake = root / "engine"
                fake.write_text(FAKE_ENGINE)
                fake.chmod(0o755)
                env = {**os.environ, "HOME": str(home),
                       "JV_API_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
                       "JV_API_USERNAME": "user", "JV_API_PASSWORD": "pass",
                       "JVCLI_CODEX_BIN": str(fake), "JVCLI_HOME": str(root / "state"),
                       "JVCLI_POLL_INTERVAL": "0.01", "JVCLI_WAIT_TIMEOUT": "3"}
                result = subprocess.run([sys.executable, "-B", str(ROOT / "bin/jvcli"),
                    "exec", "--json", "test task"], cwd=workspace, env=env,
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                self.assertTrue(Handler.saw_logout)
                self.assertEqual(Handler.job_count, len(answers))
                self.assertIn("Requesting corrected response", result.stderr)
                self.assertNotIn("e2e-token", result.stdout + result.stderr)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                if success:
                    self.assertIn("E2E done", result.stdout)
                    self.assertEqual(sum(e["type"] == "item.started" for e in events), 1)
                else:
                    self.assertNotIn("E2E done", result.stdout)
                    self.assertFalse(any(e["type"] in ("item.started", "turn.completed") for e in events))
                    self.assertEqual(result.stderr.count("Response correction stopped"), 1)
                    self.assertIn("jvcli job job_3 --json", result.stderr)
                metadata = json.loads(next((root / "state/runs").glob("*/session.json")).read_text())
                self.assertEqual(metadata["model_requests"], len(answers))
                self.assertEqual(metadata["response_repairs"], 2)
                self.assertEqual(metadata["last_exit_code"], result.returncode)
                self.assertEqual(metadata["last_job_id"], f"job_{len(answers)}")
                self.assertNotIn("e2e-token", json.dumps(metadata))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_corrections_complete_tool_loop_and_save_counts(self):
        self.recovery_case([
            "I'm having a hard time fulfilling your request. Can I help you with something else instead?",
            '{"type":"custom_tool_call","name":"apply_patch","input":"TRUNCATED',
            '{"type":"tool_call","name":"shell_command","arguments":{"command":"pwd","timeout_ms":10000}}',
            '{"type":"final","text":"E2E done"}',
        ], success=True)

    def test_exhausted_corrections_fail_and_logout_without_tool_events(self):
        self.recovery_case(["I encountered an error doing what you asked. Could you try again?"] * 3,
                           success=False)

    def test_login_adapter_tool_loop_and_logout(self):
        E2EJvHandler.job_count = 0
        E2EJvHandler.jobs = {}
        E2EJvHandler.saw_logout = False
        E2EJvHandler.submitted = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), E2EJvHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                fake = Path(td) / "codex"
                fake.write_text(FAKE_ENGINE)
                fake.chmod(0o755)
                env = os.environ.copy()
                env.update(
                    {
                        "JV_API_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
                        "JV_API_USERNAME": "user",
                        "JV_API_PASSWORD": "pass",
                        "JVCLI_CODEX_BIN": str(fake),
                        "JVCLI_HOME": str(Path(td) / "state"),
                        "JVCLI_POLL_INTERVAL": "0.01",
                        "JVCLI_WAIT_TIMEOUT": "3",
                    }
                )
                result = subprocess.run(
                    [sys.executable, str(ROOT / "bin" / "jvcli"), "exec", "test task"],
                    cwd=td,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
                self.assertIn("Signed in as user", result.stderr)
                self.assertIn("running: pwd", result.stderr)
                self.assertIn("E2E done", result.stdout)
                self.assertTrue(E2EJvHandler.saw_logout)
                self.assertEqual(E2EJvHandler.job_count, 2)
                self.assertTrue(any("tool result" in body.lower() for body in E2EJvHandler.submitted[1:]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
