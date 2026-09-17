import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

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
        with self.assertRaises(Exception):
            McpServer(".")


if __name__ == "__main__":
    unittest.main()
