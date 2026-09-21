import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from mcp.control_client import (
    ControlClient,
    ControlConfigurationError,
    ControlProtocolError,
)


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


if __name__ == "__main__":
    unittest.main()
