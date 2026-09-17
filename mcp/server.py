"""Small stdio MCP adapter over the authenticated local control daemon."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .control_client import ControlClient, ControlClientError


def _tool(
    name: str, description: str, properties: dict, required: list[str] | None = None
):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS = {
    "get_runtime_status": (
        "status",
        {},
        _tool("get_runtime_status", "Read current Veyra runtime status.", {}),
    ),
    "start_runtime": (
        "command",
        {"name": "start", "args": {}},
        _tool("start_runtime", "Start configured playback.", {}),
    ),
    "stop_runtime": (
        "stop",
        {},
        _tool("stop_runtime", "Stop the supervised playback runtime.", {}),
    ),
    "restart_runtime": (
        "command",
        {"name": "restart", "args": {}},
        _tool("restart_runtime", "Reset the active Veyra session.", {}),
    ),
    "open_dataset": (
        "open_dataset",
        {},
        _tool(
            "open_dataset",
            "Validate and open a supported dataset using the Veyra production defaults.",
            {
                "dataset": {"type": "string"},
                "root": {"type": "string"},
                "sequence": {"type": "string"},
            },
            ["dataset", "root"],
        ),
    ),
    "get_dataset_info": (
        "datasets",
        {},
        _tool(
            "get_dataset_info",
            "Inspect a supported dataset root.",
            {"dataset": {"type": "string"}, "root": {"type": "string"}},
            ["dataset", "root"],
        ),
    ),
    "play": (
        "command",
        {"name": "start", "args": {}},
        _tool("play", "Begin configured playback.", {}),
    ),
    "pause": (
        "command",
        {"name": "pause", "args": {}},
        _tool("pause", "Pause playback.", {}),
    ),
    "seek": (
        "command",
        {"name": "seek", "args": {}},
        _tool(
            "seek",
            "Seek to a frame in the configured sequence.",
            {"index": {"type": "integer", "minimum": 0}},
            ["index"],
        ),
    ),
    "set_policy": (
        "command",
        {"name": "policy", "args": {}},
        _tool(
            "set_policy",
            "Select a configured map policy.",
            {"policy": {"type": "string"}},
            ["policy"],
        ),
    ),
    "set_layer": (
        "command",
        {"name": "layer", "args": {}},
        _tool(
            "set_layer",
            "Select the visual evidence layer shown by Veyra.",
            {"layer": {"type": "string"}},
            ["layer"],
        ),
    ),
    "get_metrics": (
        "status",
        {},
        _tool("get_metrics", "Read measured runtime and map metrics.", {}),
    ),
    "get_map_statistics": (
        "diagnostics",
        {},
        _tool("get_map_statistics", "Read measured map statistics.", {}),
    ),
    "get_perception_statistics": (
        "diagnostics",
        {},
        _tool("get_perception_statistics", "Read measured perception statistics.", {}),
    ),
    "run_validation": (
        "config_validate",
        {},
        _tool(
            "run_validation",
            "Validate a Veyra session configuration.",
            {"config": {"type": "object"}},
            ["config"],
        ),
    ),
    "run_benchmark": (
        "command",
        {"name": "benchmark", "args": {}},
        _tool(
            "run_benchmark",
            "Run the configured reproducible benchmark.",
            {
                "dataset": {"type": "string"},
                "sequence": {"type": "string"},
                "count": {"type": "integer"},
            },
            ["dataset", "sequence", "count"],
        ),
    ),
    "get_recent_errors": (
        "diagnostics",
        {},
        _tool(
            "get_recent_errors",
            "Read bounded runtime diagnostics and recent errors.",
            {},
        ),
    ),
    "export_diagnostics": (
        "diagnostics",
        {},
        _tool("export_diagnostics", "Return bounded diagnostics for export.", {}),
    ),
}

SUPPORTED_DATASETS = frozenset(("rellis3d", "semanticposs", "semantickitti", "generic"))


class McpServer:
    def __init__(self, repo: str | Path | None = None):
        del repo  # Retained for the stdio entrypoint; the daemon owns repository state.
        self.control = ControlClient.from_env()

    def handle(self, request: dict) -> dict:
        request_id = request.get("id")
        method = request.get("method")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "veyra", "version": "0.1.0"},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": [entry[2] for entry in TOOLS.values()]},
            }
        if method != "tools/call":
            return self._error(request_id, -32601, f"unsupported MCP method: {method}")

        params = request.get("params") or {}
        name = params.get("name")
        entry = TOOLS.get(name)
        if entry is None:
            return self._tool_error(request_id, f"unsupported Veyra tool: {name}")
        arguments = params.get("arguments") or {}
        try:
            _validate_arguments(entry[2]["inputSchema"], arguments)
            command, fixed_args, _ = entry
            if (
                name in ("open_dataset", "get_dataset_info")
                and arguments["dataset"] not in SUPPORTED_DATASETS
            ):
                raise ValueError("unsupported dataset format")
            args = dict(fixed_args)
            if command == "command":
                args["args"] = {**args.get("args", {}), **arguments}
            else:
                args.update(arguments)
            result = self.control.request(command, args)
        except (ValueError, ControlClientError) as error:
            return self._tool_error(request_id, _error_text(error))
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result, sort_keys=True)}
                ],
                "structuredContent": result,
                "isError": False,
            },
        }

    @staticmethod
    def _tool_error(request_id, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": message}], "isError": True},
        }

    @staticmethod
    def _error(request_id, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def close(self):
        return None


def _validate_arguments(schema: dict, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    properties = schema["properties"]
    unknown = set(arguments) - set(properties)
    if unknown:
        raise ValueError(f"unknown tool argument: {sorted(unknown)[0]}")
    missing = set(schema.get("required", ())) - set(arguments)
    if missing:
        raise ValueError(f"missing tool argument: {sorted(missing)[0]}")
    for name, value in arguments.items():
        expected = properties[name]["type"]
        valid = (
            (expected == "string" and isinstance(value, str))
            or (
                expected == "integer"
                and isinstance(value, int)
                and not isinstance(value, bool)
            )
            or (expected == "object" and isinstance(value, dict))
        )
        if not valid:
            raise ValueError(f"tool argument {name} must be {expected}")
        if "minimum" in properties[name] and value < properties[name]["minimum"]:
            raise ValueError(f"tool argument {name} is below minimum")


def _error_text(error: Exception) -> str:
    if hasattr(error, "code"):
        payload = {"code": error.code, "message": error.message}
        if error.details is not None:
            payload["details"] = error.details
        return json.dumps(payload, sort_keys=True)
    return str(error)


def serve(repo: str | Path):
    server = McpServer(repo)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                response = server.handle(json.loads(line))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                response = server._error(None, -32600, str(error))
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    finally:
        server.close()


if __name__ == "__main__":
    serve(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd())
