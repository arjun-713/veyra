"""Small stdio MCP adapter over the existing Veyra ProductRuntime.

Only named product operations are exposed. The adapter never accepts shell,
arbitrary process, or arbitrary filesystem commands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from runtime.service import ProductRuntime


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
        "start",
        {},
        _tool("start_runtime", "Start configured playback.", {}),
    ),
    "stop_runtime": (
        "shutdown",
        {},
        _tool("stop_runtime", "Stop the supervised playback runtime.", {}),
    ),
    "restart_runtime": (
        "reset",
        {},
        _tool("restart_runtime", "Reset the active Veyra session.", {}),
    ),
    "open_dataset": (
        "datasets",
        {},
        _tool(
            "open_dataset",
            "Inspect a supported dataset root and return available sequences.",
            {"dataset": {"type": "string"}, "root": {"type": "string"}},
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
    "play": ("start", {}, _tool("play", "Begin configured playback.", {})),
    "pause": ("pause", {}, _tool("pause", "Pause playback.", {})),
    "seek": (
        "seek",
        {},
        _tool(
            "seek",
            "Seek to a frame in the configured sequence.",
            {"index": {"type": "integer", "minimum": 0}},
            ["index"],
        ),
    ),
    "set_policy": (
        "policy",
        {},
        _tool(
            "set_policy",
            "Select a configured map policy.",
            {"policy": {"type": "string"}},
            ["policy"],
        ),
    ),
    "set_layer": (
        "layer",
        {},
        _tool(
            "set_layer",
            "Select the visual evidence layer shown by Veyra.",
            {"layer": {"type": "string"}},
            ["layer"],
        ),
    ),
    "get_metrics": (
        "metrics",
        {},
        _tool("get_metrics", "Read measured runtime and map metrics.", {}),
    ),
    "get_map_statistics": (
        "metrics",
        {},
        _tool("get_map_statistics", "Read measured map statistics.", {}),
    ),
    "get_perception_statistics": (
        "metrics",
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
        "benchmark",
        {},
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


class McpServer:
    def __init__(self, repo: str | Path):
        self.runtime = ProductRuntime(Path(repo).resolve())

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
        command, fixed_args, _ = entry
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._tool_error(request_id, "tool arguments must be an object")
        args = {**fixed_args, **arguments}
        response = self.runtime.handle(
            {"id": f"mcp-{request_id}", "command": command, "args": args}
        )
        if not response.get("ok"):
            return self._tool_error(
                request_id,
                response.get("error", {}).get("message", "runtime request failed"),
            )
        result = response.get("result")
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
        self.runtime.close()


def serve(repo: str | Path):
    server = McpServer(repo)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = server.handle(request)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                response = server._error(None, -32600, str(error))
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    finally:
        server.close()


if __name__ == "__main__":
    serve(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd())
