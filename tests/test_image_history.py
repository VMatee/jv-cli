"""Historical image replay using scripted responses, never live inference."""

import copy
import json
import struct
import tempfile
import unittest
import urllib.request
import zlib
from pathlib import Path
from unittest.mock import patch

from jvcli.adapter import AdapterRuntime, ResponsesAdapterHandler
from jvcli.cli import ENGINE_VERSION
from jvcli.images import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_TOTAL,
    validate_image_history,
    validate_image_results,
)
from jvcli.safety import JvError, ProtocolError
from jvcli.structured import StructuredProcessor
from jvcli.transport import JvApiClient, JvClientConfig
from test_structured import FakeStructuredClient, WireServer, message, response, tool
from test_structured_core import core_request
from test_structured_images import image, png


class ImageHistoryTests(unittest.TestCase):
    def test_twenty_observations_continue_and_historical_tampering_fails(self):
        pages = ["Alice p1", "Alice p2", "Bob p1", "Bob p2", "Charlie p1", "Charlie p2"]
        remote = WireServer()
        try:
            remote.create_status = 200
            client = JvApiClient(
                JvClientConfig(base_url=remote.base, poll_interval=0.001)
            )
            client._token = "SYNTHETIC-TOKEN"
            with tempfile.TemporaryDirectory() as td:
                processor = StructuredProcessor(client, Path(td))
                runtime = AdapterRuntime(client, processor=processor)
                port = runtime.start()
                try:
                    request = core_request()
                    request["stream"] = False
                    results = []
                    for i, page in enumerate(
                        pages + [f"synthetic {n}" for n in range(7, 21)]
                    ):
                        output = {
                            **tool(
                                json.dumps({"path": page + ".png"}),
                                name="view_image",
                                call_id=f"view_{i}",
                            ),
                            "id": f"fc_{i}",
                        }
                        remote.create_payload = response(
                            output=[output], response_id=f"response_{i}"
                        )
                        wire = urllib.request.Request(
                            f"http://127.0.0.1:{port}/v1/responses",
                            data=json.dumps(request).encode(),
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": "Bearer " + runtime.key,
                            },
                        )
                        with urllib.request.urlopen(wire, timeout=3) as stream:
                            self.assertEqual(json.load(stream)["output"], [output])
                        sent = json.loads(remote.posts[-1][2])
                        if i:
                            self.assertEqual(
                                sent["previous_response_id"], f"response_{i - 1}"
                            )
                            self.assertEqual(sent["input"], [results[-1]])
                        self.assertEqual(
                            [
                                item
                                for item in request["input"]
                                if item.get("type") == "function_call_output"
                            ],
                            results,
                        )
                        label = b"Page\0" + page.encode()
                        chunk = (
                            struct.pack(">I", len(label))
                            + b"tEXt"
                            + label
                            + struct.pack(">I", zlib.crc32(b"tEXt" + label))
                        )
                        result = {
                            "type": "function_call_output",
                            "call_id": output["call_id"],
                            "output": [image(png()[:-12] + chunk + png()[-12:])],
                        }
                        results.append(result)
                        request["input"] += [output, result]
                    remote.create_payload = response(
                        output=[message()], response_id="response_final"
                    )
                    self.assertEqual(runtime.process_request(request), [message()])
                    self.assertEqual(len(remote.posts), 21)
                    self.assertEqual(runtime.response_repairs, 0)
                    resumed = AdapterRuntime(
                        client, processor=StructuredProcessor(client, Path(td))
                    )
                    self.assertEqual(resumed.process_request(request), [message()])
                    self.assertEqual(len(remote.posts), 21)
                    for change in ("bytes", "path", "call_id"):
                        altered = copy.deepcopy(request)
                        if change == "bytes":
                            altered["input"][2]["output"] = [image()]
                        elif change == "path":
                            altered["input"][1]["arguments"] = (
                                '{"path":"different.png"}'
                            )
                        else:
                            altered["input"][2]["call_id"] = "different_call"
                        with (
                            self.subTest(change=change),
                            self.assertRaises(ProtocolError),
                        ):
                            resumed.process_request(altered)
                        self.assertEqual(len(remote.posts), 21)
                finally:
                    runtime.close()
        finally:
            remote.close()

    def test_history_validates_each_image_and_current_result_byte_budget(self):
        for value in (
            {**image(), "image_url": "file:///etc/passwd"},
            {**image(), "image_url": "data:image/jpeg;base64,AAAA"},
            image(png() + b"x" * MAX_IMAGE_BYTES),
        ):
            with (
                self.subTest(value_type=value["type"]),
                self.assertRaises(ProtocolError),
            ):
                validate_image_history(
                    [{"type": "function_call_output", "output": [value]}]
                )
        part = image(png() + b"x" * (MAX_IMAGE_TOTAL // 3))
        with self.assertRaisesRegex(ProtocolError, "12 MiB"):
            validate_image_results([part] * 3)
        # Accumulated historical bytes are not the active image budget.
        validate_image_history([{"type": "function_call_output", "output": [part]}] * 3)

    def test_task_and_durable_round_budgets_are_separate_from_images(self):
        for budget in ("model", "durable"):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as td:
                responses = [
                    response(
                        output=[
                            tool(name="view_image", arguments='{"path":"image.png"}')
                        ]
                    )
                ]
                client = FakeStructuredClient(responses)
                runtime = AdapterRuntime(
                    client,
                    max_requests=1,
                    processor=StructuredProcessor(client, Path(td)),
                )
                request = core_request()
                call = runtime.process_request(request)[0]
                request["input"] += [
                    call,
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": [image()],
                    },
                ]
                with (
                    patch(
                        "jvcli.structured.MAX_ROUNDS", 1 if budget == "durable" else 500
                    ),
                    self.assertRaisesRegex(JvError, "limit reached"),
                ):
                    runtime.process_request(request)
                self.assertEqual(len(client.posts), 1)

    def test_completion_opens_gate_before_immediate_continuation(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming), tempfile.TemporaryDirectory() as td:
                client = FakeStructuredClient([response(output=[message()])])
                runtime = AdapterRuntime(
                    client, processor=StructuredProcessor(client, Path(td))
                )
                port = runtime.start()
                method = "_finish_sse" if streaming else "_json_response"
                original = getattr(ResponsesAdapterHandler, method)
                observed = []

                def check_gate(handler, *args, observed=observed, original=original):
                    observed.append(handler.runtime.lock.locked())
                    return original(handler, *args)

                try:
                    request = core_request()
                    request["stream"] = streaming
                    wire = urllib.request.Request(
                        f"http://127.0.0.1:{port}/v1/responses",
                        data=json.dumps(request).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": "Bearer " + runtime.key,
                        },
                    )
                    with (
                        patch.object(ResponsesAdapterHandler, method, check_gate),
                        urllib.request.urlopen(wire, timeout=3) as stream,
                    ):
                        stream.read()
                    self.assertEqual(observed, [False])
                finally:
                    runtime.close()

    def test_text_history_and_engine_pin(self):
        validate_image_history("ordinary text")
        validate_image_history([{"role": "user", "content": "ordinary text"}])
        self.assertEqual(ENGINE_VERSION, "0.149.1")
