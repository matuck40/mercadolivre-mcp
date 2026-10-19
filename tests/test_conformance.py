"""Validate server output against the official MCP JSON Schema (vendored, offline)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mercadolivre_mcp.server import SUPPORTED_PROTOCOL_VERSIONS, Server
from mercadolivre_mcp.tools import TOOLS

SCHEMA = json.loads(
    (Path(__file__).parent / "fixtures" / "mcp-schema-2025-11-25.json").read_text(encoding="utf-8")
)


def validate(instance, definition):
    schema = {"$ref": f"#/$defs/{definition}", "$defs": SCHEMA["$defs"]}
    Draft202012Validator(schema).validate(instance)


@pytest.fixture
def server(client):
    return Server(TOOLS, lambda: client)


def rpc(server, method, params=None, msg_id=1):
    message = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def test_initialize_result_matches_schema(server):
    params = {
        "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[0],
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }
    response = rpc(server, "initialize", params)
    validate(response["result"], "InitializeResult")


def test_tools_list_result_matches_schema(server):
    response = rpc(server, "tools/list")
    validate(response["result"], "ListToolsResult")
    assert len(response["result"]["tools"]) == 10


def test_tool_call_result_matches_schema(server, fake_ml):
    fake_ml.route("GET", "/users/me", body={"id": 123, "nickname": "TESTUSER"})
    ok = rpc(server, "tools/call", {"name": "ml_get_account", "arguments": {}})
    validate(ok["result"], "CallToolResult")
    assert not ok["result"].get("isError")

    failed = rpc(server, "tools/call", {"name": "ml_get_item", "arguments": {}})
    validate(failed["result"], "CallToolResult")
    assert failed["result"]["isError"] is True


def test_jsonrpc_envelopes_match_schema(server):
    success = rpc(server, "ping", msg_id=7)
    validate(success, "JSONRPCResultResponse")
    validate(success, "JSONRPCResponse")
    unknown = rpc(server, "no/such/method", msg_id="abc")
    validate(unknown, "JSONRPCErrorResponse")
    validate(unknown, "JSONRPCResponse")
    validate(rpc(server, "tools/call", {"name": "nope"}), "JSONRPCErrorResponse")
    # JSON-RPC 2.0 requires "id": null when the request id is unknown (parse error). The MCP
    # schema types id as string|integer, so only the rest of the envelope is validated.
    parse_error = server.handle_line("{not json")
    assert parse_error["id"] is None
    validate({k: v for k, v in parse_error.items() if k != "id"}, "JSONRPCErrorResponse")


def test_stdio_handshake_subprocess(tmp_path):
    lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = "".join(json.dumps(line) + "\n" for line in lines)
    env = {"ML_SECRETS_DIR": str(tmp_path), "PATH": os.environ.get("PATH", "")}
    proc = subprocess.run(  # noqa: S603 - fixed argv, test only
        [sys.executable, "-m", "mercadolivre_mcp"],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    out_lines = proc.stdout.splitlines()
    assert len(out_lines) == 2, proc.stdout
    first, second = (json.loads(line) for line in out_lines)
    assert first["id"] == 1
    assert second["id"] == 2
    validate(first["result"], "InitializeResult")
    validate(second["result"], "ListToolsResult")
    assert len(second["result"]["tools"]) == 10
    assert proc.stderr == ""
