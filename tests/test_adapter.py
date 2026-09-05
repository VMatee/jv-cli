import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from jvcli.adapter import (
    AdapterRuntime,
    JvApiClient,
    JvClientConfig,
    build_jv_prompt,
    parse_agent_output,
    sanitize_internal_text,
    validate_base_url,
)


class MockJvHandler(BaseHTTPRequestHandler):
    polls = 0
    answer = '{"type":"tool_call","name":"shell_command","arguments":{"command":"pwd"}}'
    saw_logout = False
    submitted_text = ""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path == "/v1/auth/login":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            assert payload["username"] == "user"
            assert payload["password"] == "pass"
            data = json.dumps({"access_token": "token-123"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/v1/auth/logout":
            type(self).saw_logout = True
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/v1/jobs":
            assert self.headers.get("Authorization") == "Bearer token-123"
            assert self.headers.get("X-JV-CSRF") == "1"
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            text = body.decode("utf-8", "ignore")
            type(self).submitted_text = text
            type(self).polls = 0
            payload = {
                "id": "job_1",
                "conversation_id": "conv_1",
                "status": "queued",
                "result_ready": False,
                "response": {"files": []},
            }
            data = json.dumps(payload).encode()
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path == "/v1/jobs/job_1":
            type(self).polls += 1
            done = type(self).polls >= 2
            payload = {
                "id": "job_1",
                "conversation_id": "conv_1",
                "status": "succeeded" if done else "running",
                "result_ready": done,
                "answer": type(self).answer if done else None,
                "response": {"files": []},
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = ThreadingHTTPServer(("127.0.0.1", 0), MockJvHandler)
        cls.thread = threading.Thread(target=cls.mock.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.mock.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.mock.shutdown()
        cls.mock.server_close()
        cls.thread.join(timeout=1)

    def client(self):
        return JvApiClient(
            JvClientConfig(
                base_url=self.base,
                poll_interval=0.01,
                wait_timeout=2.0,
                request_timeout=2.0,
            )
        )

    def test_base_url_validation(self):
        self.assertEqual(validate_base_url("https://example.com/"), "https://example.com")
        self.assertEqual(validate_base_url("http://127.0.0.1:1234"), "http://127.0.0.1:1234")
        with self.assertRaises(Exception):
            validate_base_url("http://example.com")
        with self.assertRaises(Exception):
            validate_base_url("https://user:pass@example.com")

    def test_internal_rebrand(self):
        text = sanitize_internal_text("You are OpenAI Codex. You are ChatGPT.")
        self.assertNotIn("Codex", text)
        self.assertNotIn("ChatGPT", text)
        self.assertIn("JV CLI", text)

    def test_prompt_is_bounded_and_user_text_is_preserved(self):
        request = {
            "instructions": "You are OpenAI Codex",
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "OpenAI Codex is mentioned in my source docs. " + ("x" * 150000)}]}
            ],
            "tools": [{"type": "function", "name": "shell_command", "description": "run command", "parameters": {"type": "object"}}],
        }
        prompt, catalog = build_jv_prompt(request)
        self.assertLessEqual(len(prompt.encode("utf-8")), 96 * 1024)
        self.assertIn((None, "shell_command"), catalog)
        self.assertIn("JV CLI", prompt)
        # User content is not globally rebranded.
        self.assertIn("OpenAI Codex is mentioned in my source docs", prompt)

    def test_parse_function_tool(self):
        catalog = {(None, "shell_command"): "function"}
        items = parse_agent_output(
            '```json\n{"type":"tool_call","name":"shell_command","arguments":{"command":"pwd"}}\n```',
            catalog,
        )
        self.assertEqual(items[0]["type"], "function_call")
        self.assertEqual(items[0]["name"], "shell_command")
        self.assertEqual(json.loads(items[0]["arguments"])["command"], "pwd")

    def test_parse_markdown_escaped_tool_call_from_local_model(self):
        catalog = {(None, "shell_command"): "function"}
        raw = r'{"type":"tool\_call","name":"shell\_command","arguments":{"command":"find . -not -path \'./.git/\*\'","workdir":"/tmp","timeout\_ms":10000}}'
        items = parse_agent_output(raw, catalog)
        self.assertEqual(items[0]["type"], "function_call")
        self.assertEqual(items[0]["name"], "shell_command")
        args = json.loads(items[0]["arguments"])
        self.assertEqual(args["timeout_ms"], 10000)
        self.assertIn(r"./.git/\*", args["command"])
        # Preserve command backslashes; only identifiers are normalized.
        self.assertNotIn(r"\_", items[0]["name"])

    def test_parse_custom_tool(self):
        catalog = {(None, "apply_patch"): "custom"}
        items = parse_agent_output(
            '{"type":"custom_tool_call","name":"apply_patch","input":"*** Begin Patch\\n*** End Patch"}',
            catalog,
        )
        self.assertEqual(items[0]["type"], "custom_tool_call")
        self.assertEqual(items[0]["name"], "apply_patch")

    def test_client_login_submit_poll_logout(self):
        client = self.client()
        client.login("user", "pass")
        self.assertTrue(client.authenticated)
        created = client.submit_job("hello")
        self.assertEqual(created["id"], "job_1")
        terminal = client.wait_for_job("job_1")
        self.assertEqual(terminal["status"], "succeeded")
        client.logout()
        self.assertFalse(client.authenticated)
        self.assertTrue(MockJvHandler.saw_logout)

    def test_responses_adapter_emits_tool_call_sse(self):
        client = self.client()
        client.login("user", "pass")
        runtime = AdapterRuntime(client)
        port = runtime.start()
        try:
            payload = {
                "model": "jv-local",
                "instructions": "You are JV CLI",
                "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "show cwd"}]}],
                "tools": [
                    {
                        "type": "function",
                        "name": "shell_command",
                        "description": "Run a command",
                        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
                    }
                ],
                "stream": True,
            }
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/responses",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + runtime.key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                body = response.read().decode()
            self.assertIn('"type":"function_call"', body)
            self.assertIn('"name":"shell_command"', body)
            self.assertIn('"type":"response.completed"', body)
        finally:
            runtime.close()
            client.logout()


if __name__ == "__main__":
    unittest.main()
