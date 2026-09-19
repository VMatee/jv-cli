"""Synthetic shell syntax feedback and unchanged repeated-action fencing."""

import json
import tempfile
import unittest
from pathlib import Path

from jvcli.adapter import AdapterRuntime
from jvcli.safety import ProtocolError
from jvcli.structured import StructuredProcessor
from test_structured import FakeStructuredClient, local_request, response, tool


class ShellFailureTests(unittest.TestCase):
    def test_complete_syntax_error_reaches_next_round_and_fourth_action_is_rejected(
        self,
    ):
        command = 'body="$(printf %s [fixture](http://127.0.0.1:8766))"'
        failure = "Exit code: 2\n/bin/bash: syntax error near unexpected token `('\n"
        replies = [
            response(
                output=[
                    {
                        **tool(json.dumps({"command": command}), call_id=f"call_{n}"),
                        "id": f"fc_{n}",
                    }
                ],
                response_id=f"response_{n}",
            )
            for n in range(4)
        ]
        with tempfile.TemporaryDirectory() as directory:
            client = FakeStructuredClient(replies)
            processor = StructuredProcessor(client, Path(directory))
            runtime = AdapterRuntime(client, processor=processor)
            request = local_request()
            for n in range(3):
                call = runtime.process_request(request)[0]
                if n:
                    self.assertEqual(client.posts[n][0]["input"][0]["output"], failure)
                request["input"] += [
                    call,
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": failure,
                    },
                ]
            with self.assertRaisesRegex(ProtocolError, "same tool action four times"):
                runtime.process_request(request)
            self.assertEqual(client.posts[3][0]["input"][0]["output"], failure)
            self.assertEqual(processor.state.rounds[-1]["phase"], "rejected")
            self.assertEqual(list(runtime.signatures.values()), [3])
            self.assertEqual(len(client.posts), 4)
