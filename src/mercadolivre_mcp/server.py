"""Line-delimited JSON-RPC 2.0 server speaking MCP over stdio."""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TextIO

from . import __version__
from .errors import MLError, ToolInputError
from .tools.registry import Tool, validate_arguments

if TYPE_CHECKING:
    from .client import MLClient

SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "mercadolivre-mcp"

INSTRUCTIONS = (
    "Write tools only return a preview of the change; send confirm=true only after "
    "the human has seen the preview and approved it."
)


def _result(msg_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


class Server:
    def __init__(
        self,
        tools: Mapping[str, Tool],
        client_factory: Callable[[], MLClient],
        stderr: TextIO | None = None,
    ):
        self.tools = tools
        self._client_factory = client_factory
        self._client: MLClient | None = None
        self._stderr = stderr

    def _log_traceback(self) -> None:
        traceback.print_exc(file=self._stderr if self._stderr is not None else sys.stderr)

    def handle_line(self, line: str) -> dict | None:
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):  # RecursionError: absurdly nested input
            return _error(None, -32700, "Parse error")
        return self.handle(message)

    def handle(self, message: Any) -> dict | None:
        try:
            return self._dispatch(message)
        except Exception:
            self._log_traceback()
            msg_id = message.get("id") if isinstance(message, dict) else None
            return _error(msg_id, -32603, "Internal error")

    def _dispatch(self, message: Any) -> dict | None:
        if not isinstance(message, dict):
            return _error(None, -32600, "Invalid Request")
        method = message.get("method")
        if "id" not in message:
            if isinstance(method, str):
                return None  # notification: never answered
            return _error(None, -32600, "Invalid Request")
        msg_id = message["id"]
        if (
            not isinstance(method, str)
            or msg_id is None
            or isinstance(msg_id, bool)
            or not isinstance(msg_id, (str, int))
        ):
            return _error(None, -32600, "Invalid Request")
        params = message.get("params")
        if params is None:
            params = {}
        if method == "initialize":
            return _result(msg_id, self._initialize(params))
        if method == "ping":
            return _result(msg_id, {})
        if method == "tools/list":
            return _result(msg_id, {"tools": [t.to_mcp() for t in self.tools.values()]})
        if method == "tools/call":
            return self._tools_call(msg_id, params)
        return _error(msg_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _initialize(params: Any) -> dict:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    def _get_client(self) -> MLClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _tools_call(self, msg_id: Any, params: Any) -> dict:
        if not isinstance(params, dict):
            return _error(msg_id, -32602, "Invalid params")
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return _error(msg_id, -32602, f"Unknown tool: {name}")
        arguments = params.get("arguments")
        if arguments is None:  # some clients send null for tools without arguments
            arguments = {}
        try:
            args = validate_arguments(tool.input_schema, arguments)
            data = tool.handler(self._get_client(), args)
        except ToolInputError as exc:
            return _result(msg_id, _tool_error(str(exc)))
        except MLError as exc:
            return _result(msg_id, _tool_error(f"Error: {exc}"))
        except Exception as exc:
            # The message may hold anything (even a header value), so it stays in the log.
            self._log_traceback()
            return _result(
                msg_id,
                _tool_error(
                    f"Unexpected error ({type(exc).__name__}). See the server log for details."
                ),
            )
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return _result(
            msg_id, {"content": [{"type": "text", "text": text}], "structuredContent": data}
        )

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        for line in stdin:
            if not line.strip():
                continue
            response = self.handle_line(line)
            if response is None:
                continue
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
