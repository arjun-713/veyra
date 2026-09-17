"""Authenticated, bounded client for the local Veyra control daemon."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from pathlib import Path
from typing import Any


MAX_FRAME_BYTES = 64 * 1024
MAX_ID_BYTES = 128
MAX_COMMAND_BYTES = 64
CONNECT_TIMEOUT = 2.0
IO_TIMEOUT = 2.0


class ControlClientError(Exception):
    """Base class for configuration, transport, and protocol failures."""


class ControlConfigurationError(ControlClientError):
    pass


class ControlTransportError(ControlClientError):
    pass


class ControlProtocolError(ControlClientError):
    pass


class ControlDaemonError(ControlClientError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


class ControlClient:
    def __init__(
        self,
        endpoint: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, int],
        token: str,
    ):
        self.endpoint = endpoint
        self.token = token
        self._next_id = 1

    @classmethod
    def from_env(cls) -> "ControlClient":
        endpoint_value = os.environ.get("VEYRA_CONTROL_ENDPOINT")
        if not endpoint_value:
            raise ControlConfigurationError(
                "VEYRA_CONTROL_ENDPOINT is required for the local control daemon"
            )
        endpoint = _parse_endpoint(endpoint_value)
        token_file = os.environ.get("VEYRA_CONTROL_TOKEN_FILE")
        if not token_file:
            raise ControlConfigurationError(
                "VEYRA_CONTROL_TOKEN_FILE is required for the local control daemon"
            )
        return cls(endpoint, _read_token(token_file))

    def request(self, command: str, args: dict[str, Any]) -> Any:
        if not isinstance(command, str) or not 0 < len(command) <= MAX_COMMAND_BYTES:
            raise ControlProtocolError("command must be a non-empty bounded string")
        if not isinstance(args, dict):
            raise ControlProtocolError("args must be an object")

        request_id = f"mcp-{self._next_id}"
        self._next_id += 1
        request = {
            "schema_version": 1,
            "id": request_id,
            "authorization": self.token,
            "command": command,
            "args": args,
        }
        frame = json.dumps(request, separators=(",", ":"), ensure_ascii=True).encode()
        frame += b"\n"
        if len(frame) > MAX_FRAME_BYTES:
            raise ControlProtocolError("control request exceeds 64 KiB")

        try:
            with socket.create_connection(self.endpoint, CONNECT_TIMEOUT) as stream:
                stream.settimeout(IO_TIMEOUT)
                stream.sendall(frame)
                response_frame = stream.makefile("rb").readline(MAX_FRAME_BYTES + 1)
        except OSError as error:
            raise ControlTransportError(
                f"cannot connect to control endpoint {self.endpoint[0]}:{self.endpoint[1]}: {error}"
            ) from error
        if not response_frame:
            raise ControlProtocolError("control response was empty")
        if len(response_frame) > MAX_FRAME_BYTES:
            raise ControlProtocolError("control response exceeds 64 KiB")
        try:
            response = json.loads(response_frame)
        except json.JSONDecodeError as error:
            raise ControlProtocolError(
                f"malformed control response: {error}"
            ) from error
        return _validate_response(response, request_id)


def _parse_endpoint(
    value: str,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, int]:
    host: str
    port_text: str
    if value.startswith("[") and "]" in value:
        host, separator, port_text = value[1:].partition("]:")
        if not separator:
            raise ControlConfigurationError(
                "VEYRA_CONTROL_ENDPOINT must be a loopback SocketAddr"
            )
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            raise ControlConfigurationError(
                "VEYRA_CONTROL_ENDPOINT must be a loopback SocketAddr"
            )
    try:
        address = ipaddress.ip_address(host)
        port = int(port_text)
    except ValueError as error:
        raise ControlConfigurationError(
            "VEYRA_CONTROL_ENDPOINT must be a loopback SocketAddr"
        ) from error
    if not address.is_loopback or address.is_unspecified or not 1 <= port <= 65535:
        raise ControlConfigurationError(
            "VEYRA_CONTROL_ENDPOINT must use a loopback address"
        )
    return address, port


def _read_token(path: str) -> str:
    try:
        token = Path(path).read_bytes().rstrip(b"\r\n")
    except OSError as error:
        raise ControlConfigurationError(
            f"cannot read control token file {path}: {error}"
        ) from error
    if not 32 <= len(token) <= 256 or not all(33 <= byte <= 126 for byte in token):
        raise ControlConfigurationError(
            "control token must contain 32-256 printable ASCII bytes"
        )
    return token.decode("ascii")


def _validate_response(response: Any, expected_id: str) -> Any:
    if not isinstance(response, dict):
        raise ControlProtocolError("control response must be an object")
    response_id = response.get("id")
    if (
        not isinstance(response_id, str)
        or len(response_id) > MAX_ID_BYTES
        or response_id != expected_id
    ):
        raise ControlProtocolError("control response id did not match the request")
    ok = response.get("ok")
    if not isinstance(ok, bool):
        raise ControlProtocolError("control response ok must be a boolean")
    if ok:
        if "result" not in response:
            raise ControlProtocolError("successful control response lacks result")
        return response["result"]
    error = response.get("error")
    if not isinstance(error, dict):
        raise ControlProtocolError("failed control response lacks error object")
    code = error.get("code")
    message = error.get("message")
    if (
        not isinstance(code, str)
        or not code
        or not isinstance(message, str)
        or not message
    ):
        raise ControlProtocolError(
            "control error code and message must be non-empty strings"
        )
    raise ControlDaemonError(code, message, error.get("details"))
