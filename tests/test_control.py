"""Control regression suite."""

import json
import os
import socketserver
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from mcp.control_client import (
    ControlClient,
    ControlConfigurationError,
    ControlProtocolError,
)
from mcp.server import McpServer

# Mcp control client


class OneShotDaemon:
    def __init__(self, response):
        self.response = response
        self.request = None
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
                daemon.request = json.loads(frame)
                response = dict(daemon.response)
                response.setdefault("id", daemon.request.get("id"))
                self.response = BytesIO(json.dumps(response).encode() + b"\n")

            def makefile(self, *_args):
                return self.response

        return Connection()

    def close(self):
        return None


class ControlClientTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.token = Path(self.tempdir.name) / "token"
        self.token.write_text("x" * 32 + "\r\n")
        os.environ["VEYRA_CONTROL_TOKEN_FILE"] = str(self.token)

    def tearDown(self):
        os.environ.pop("VEYRA_CONTROL_ENDPOINT", None)
        os.environ.pop("VEYRA_CONTROL_TOKEN_FILE", None)
        if hasattr(self, "daemon"):
            self.daemon.close()
        if hasattr(self, "transport"):
            self.transport.stop()
        self.tempdir.cleanup()

    def test_rejects_non_loopback_endpoint(self):
        os.environ["VEYRA_CONTROL_ENDPOINT"] = "192.0.2.1:1234"
        with self.assertRaises(ControlConfigurationError):
            ControlClient.from_env()

    def test_rejects_invalid_token(self):
        self.token.write_text("short")
        os.environ["VEYRA_CONTROL_ENDPOINT"] = "127.0.0.1:1234"
        with self.assertRaises(ControlConfigurationError):
            ControlClient.from_env()

    def test_rejects_oversized_request_before_connecting(self):
        os.environ["VEYRA_CONTROL_ENDPOINT"] = "127.0.0.1:1234"
        client = ControlClient.from_env()
        with self.assertRaises(ControlProtocolError):
            client.request("status", {"value": "x" * (64 * 1024)})

    def test_sends_contract_request_and_returns_result(self):
        self.daemon = OneShotDaemon({"ok": True, "result": {"state": "ready"}})
        os.environ["VEYRA_CONTROL_ENDPOINT"] = self.daemon.endpoint
        self.transport = patch(
            "mcp.control_client.socket.create_connection", self.daemon.connection
        )
        self.transport.start()
        client = ControlClient.from_env()
        self.assertEqual(client.request("status", {}), {"state": "ready"})
        self.assertEqual(self.daemon.request["schema_version"], 1)
        self.assertEqual(self.daemon.request["authorization"], "x" * 32)
        self.assertEqual(self.daemon.request["command"], "status")

    def test_rejects_mismatched_response_id(self):
        self.daemon = OneShotDaemon({"ok": True, "id": "wrong", "result": {}})
        os.environ["VEYRA_CONTROL_ENDPOINT"] = self.daemon.endpoint
        self.transport = patch(
            "mcp.control_client.socket.create_connection", self.daemon.connection
        )
        self.transport.start()
        with self.assertRaises(ControlProtocolError):
            ControlClient.from_env().request("status", {})

    def test_rejects_oversized_response(self):
        self.daemon = OneShotDaemon(
            {"ok": True, "result": {"padding": "x" * (64 * 1024)}}
        )
        os.environ["VEYRA_CONTROL_ENDPOINT"] = self.daemon.endpoint
        self.transport = patch(
            "mcp.control_client.socket.create_connection", self.daemon.connection
        )
        self.transport.start()
        with self.assertRaises(ControlProtocolError):
            ControlClient.from_env().request("status", {})

    def test_preserves_structured_daemon_error(self):
        self.daemon = OneShotDaemon(
            {
                "ok": False,
                "error": {
                    "code": "CONTROLLER_ERROR",
                    "message": "not ready",
                    "details": {"state": "booting"},
                },
            }
        )
        os.environ["VEYRA_CONTROL_ENDPOINT"] = self.daemon.endpoint
        self.transport = patch(
            "mcp.control_client.socket.create_connection", self.daemon.connection
        )
        self.transport.start()
        with self.assertRaises(Exception) as raised:
            ControlClient.from_env().request("status", {})
        self.assertEqual(raised.exception.code, "CONTROLLER_ERROR")
        self.assertEqual(raised.exception.details, {"state": "booting"})


# Mcp server


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


class DaemonMcpServerTests(unittest.TestCase):
    """Validated commands over the production authenticated control daemon."""

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

    def test_invalid_tool_arguments_never_contact_daemon(self):
        self.start_server()
        cases = (
            ("open_dataset", {"dataset": "unsafe", "root": "/tmp"}, None),
            (
                "open_dataset",
                {"dataset": "generic", "root": "/data/" + "x" * 5000},
                "maximum length",
            ),
            ("set_policy", {"policy": "turbo"}, None),
            ("set_layer", {"layer": "../../etc"}, None),
            ("seek", {"index": -1}, None),
            ("seek", {"index": 10**10}, None),
            (
                "run_benchmark",
                {"dataset": "generic", "sequence": "00", "count": 0},
                None,
            ),
            (
                "run_benchmark",
                {"dataset": "generic", "sequence": "00", "count": 10**9},
                None,
            ),
        )
        for tool, arguments, message in cases:
            with self.subTest(tool=tool, arguments=arguments):
                response = self.server.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments},
                    }
                )
                self.assertTrue(response["result"]["isError"])
                if message:
                    self.assertIn(message, response["result"]["content"][0]["text"])
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
        if ControlConfigurationError is None:
            self.skipTest("daemon control-client module is unavailable")
        with self.assertRaises(ControlConfigurationError):
            McpServer(".")


if __name__ == "__main__":
    unittest.main()
