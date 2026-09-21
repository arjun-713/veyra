import json
import os
import socketserver
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from mcp.control_client import ControlConfigurationError
from mcp.server import McpServer


class FakeDaemon:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests = []
        self.endpoint = "127.0.0.1:43210"

    def connection(self, *_args):
        daemon = self

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def settimeout(self, _timeout):
                return None

            def sendall(self, frame):
                request = json.loads(frame)
                daemon.requests.append(request)
                response = dict(
                    daemon.responses.get(request["command"], {"ok": True, "result": {}})
                )
                response["id"] = request["id"]
                self.response = BytesIO(json.dumps(response).encode() + b"\n")

            def makefile(self, *_args):
                return self.response

        return Connection()

    def close(self):
        return None


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.token_file = Path(self.tempdir.name) / "token"
        self.token_file.write_text(
            "test-control-secret-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ\n"
        )
        os.environ["VEYRA_CONTROL_TOKEN_FILE"] = str(self.token_file)

    def tearDown(self):
        os.environ.pop("VEYRA_CONTROL_ENDPOINT", None)
        os.environ.pop("VEYRA_CONTROL_TOKEN_FILE", None)
        self.tempdir.cleanup()
        if hasattr(self, "daemon"):
            self.daemon.close()
        if hasattr(self, "transport"):
            self.transport.stop()

    def start_server(self, responses=None):
        self.daemon = FakeDaemon(responses)
        os.environ["VEYRA_CONTROL_ENDPOINT"] = self.daemon.endpoint
        self.transport = patch(
            "mcp.control_client.socket.create_connection", self.daemon.connection
        )
        self.transport.start()
        self.server = McpServer(".")

    def test_tool_call_reaches_a_live_loopback_daemon(self):
        # No socket mocking: proves ControlClient completes a real TCP
        # round-trip. Regression: the parsed endpoint host was an ipaddress,
        # not str, so the first live call died in getaddrinfo (TypeError).
        received = {}

        class LiveHandler(socketserver.StreamRequestHandler):
            def handle(self):
                request = json.loads(self.rfile.readline(64 * 1024 + 1))
                received.update(request)
                reply = {
                    "ok": True,
                    "id": request.get("id"),
                    "result": {"state": "live"},
                }
                self.wfile.write((json.dumps(reply) + "\n").encode())

        daemon = socketserver.TCPServer(("127.0.0.1", 0), LiveHandler)
        thread = threading.Thread(target=daemon.handle_request, daemon=True)
        thread.start()
        os.environ["VEYRA_CONTROL_ENDPOINT"] = f"127.0.0.1:{daemon.server_address[1]}"
        server = McpServer(".")
        try:
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "get_runtime_status", "arguments": {}},
                }
            )
        finally:
            thread.join(timeout=5)
            daemon.server_close()
        self.assertFalse(response["result"]["isError"])
        self.assertIn("live", response["result"]["content"][0]["text"])
        self.assertEqual(received["command"], "status")

    def test_server_has_no_direct_product_runtime_ownership(self):
        source = Path(__file__).parents[1].joinpath("mcp", "server.py").read_text()
        self.assertNotIn("ProductRuntime", source)
        self.assertNotIn("runtime.service", source)

    def test_tool_catalog_is_safe_and_typed(self):
        self.start_server()
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("get_runtime_status", names)
        self.assertIn("set_layer", names)
        self.assertNotIn("execute_shell", names)
        self.assertTrue(
            all(
                tool["inputSchema"]["additionalProperties"] is False
                for tool in response["result"]["tools"]
            )
        )

    def test_named_tools_form_daemon_requests(self):
        self.start_server({"command": {"ok": True, "result": {"layer": "lod"}}})
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "set_layer", "arguments": {"layer": "lod"}},
            }
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(self.daemon.requests[0]["command"], "command")
        self.assertEqual(
            self.daemon.requests[0]["args"], {"name": "layer", "args": {"layer": "lod"}}
        )

    def test_stop_runtime_stops_the_runtime_without_shutting_down_control(self):
        self.start_server({"stop": {"ok": True, "result": {"state": "ready"}}})
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {"name": "stop_runtime", "arguments": {}},
            }
        )

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(self.daemon.requests[0]["command"], "stop")
        self.assertEqual(self.daemon.requests[0]["args"], {})

    def test_dataset_tool_validates_format_and_root_before_daemon(self):
        self.start_server()
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "open_dataset",
                    "arguments": {"dataset": "unsafe", "root": "/tmp"},
                },
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(self.daemon.requests, [])

    def test_open_dataset_uses_the_stateful_shared_open_operation(self):
        self.start_server(
            {
                "open_dataset": {
                    "ok": True,
                    "result": {"selected_sequence": "00"},
                }
            }
        )
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 41,
                "method": "tools/call",
                "params": {
                    "name": "open_dataset",
                    "arguments": {
                        "dataset": "semanticposs",
                        "root": "/data/semanticposs",
                        "sequence": "00",
                    },
                },
            }
        )

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(self.daemon.requests[0]["command"], "open_dataset")
        self.assertEqual(
            self.daemon.requests[0]["args"],
            {"dataset": "semanticposs", "root": "/data/semanticposs", "sequence": "00"},
        )

    def test_daemon_error_is_preserved_as_mcp_tool_error(self):
        self.start_server(
            {
                "status": {
                    "ok": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "nope",
                        "details": {"retry": False},
                    },
                }
            }
        )
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "get_runtime_status", "arguments": {}},
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("UNAUTHORIZED", response["result"]["content"][0]["text"])
        self.assertIn("retry", response["result"]["content"][0]["text"])

    def test_missing_daemon_configuration_fails_closed(self):
        os.environ.pop("VEYRA_CONTROL_ENDPOINT", None)
        with self.assertRaises(ControlConfigurationError):
            McpServer(".")

    def test_oversized_root_is_rejected_before_daemon_contact(self):
        self.start_server()
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "open_dataset",
                    "arguments": {"dataset": "generic", "root": "/data/" + "x" * 5000},
                },
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertIn("maximum length", response["result"]["content"][0]["text"])
        self.assertEqual(self.daemon.requests, [])

    def test_unknown_policy_and_layer_are_rejected_before_daemon_contact(self):
        self.start_server()
        for tool, arguments in (
            ("set_policy", {"policy": "turbo"}),
            ("set_layer", {"layer": "../../etc"}),
        ):
            response = self.server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                }
            )
            self.assertTrue(response["result"]["isError"], tool)
        self.assertEqual(self.daemon.requests, [])

    def test_out_of_range_seek_and_benchmark_counts_are_rejected(self):
        self.start_server()
        for tool, arguments in (
            ("seek", {"index": -1}),
            ("seek", {"index": 10**10}),
            ("run_benchmark", {"dataset": "generic", "sequence": "00", "count": 0}),
            (
                "run_benchmark",
                {"dataset": "generic", "sequence": "00", "count": 10**9},
            ),
        ):
            response = self.server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                }
            )
            self.assertTrue(response["result"]["isError"], f"{tool} {arguments}")
        self.assertEqual(self.daemon.requests, [])


if __name__ == "__main__":
    unittest.main()
