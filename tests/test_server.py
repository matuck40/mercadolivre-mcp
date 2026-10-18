import io
import json

from mercadolivre_mcp import __version__
from mercadolivre_mcp.errors import APIError
from mercadolivre_mcp.server import SERVER_NAME, SUPPORTED_PROTOCOL_VERSIONS, Server
from mercadolivre_mcp.tools import Tool

ECHO_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string", "minLength": 1},
        "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30},
    },
    "required": ["item_id"],
    "additionalProperties": False,
}


def _echo(client, args):
    return {"echo": args, "client": client}


def _boom(client, args):
    raise RuntimeError("kaboom")


def _api_fail(client, args):
    raise APIError("GET", "/x", 404, "nope")


def make_tools():
    def tool(name, handler, schema):
        return Tool(
            name=name,
            title=name.title(),
            description=f"{name} tool",
            input_schema=schema,
            annotations={"readOnlyHint": True},
            handler=handler,
        )

    empty = {"type": "object", "properties": {}}
    return {
        "echo": tool("echo", _echo, ECHO_SCHEMA),
        "boom": tool("boom", _boom, empty),
        "api_fail": tool("api_fail", _api_fail, empty),
    }


class Factory:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return "CLIENT"


def make_server(stderr=None):
    factory = Factory()
    server = Server(make_tools(), factory, stderr=stderr or io.StringIO())
    return server, factory


def rpc(method, params=None, id=1):
    msg = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(server, name, arguments=None):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return server.handle(rpc("tools/call", params))


def test_initialize_echoes_supported_version():
    server, _ = make_server()
    resp = server.handle(rpc("initialize", {"protocolVersion": "2025-06-18"}))
    result = resp["result"]
    assert resp["id"] == 1 and resp["jsonrpc"] == "2.0"
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": SERVER_NAME, "version": __version__}
    assert "confirm" in result["instructions"] and "preview" in result["instructions"]


def test_initialize_unsupported_version_falls_back():
    server, _ = make_server()
    resp = server.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}))
    assert resp["result"]["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]


def test_initialize_does_not_create_client():
    server, factory = make_server()
    server.handle(rpc("initialize", {"protocolVersion": "2025-06-18"}))
    server.handle(rpc("tools/list"))
    assert factory.calls == 0


def test_ping():
    server, _ = make_server()
    assert server.handle(rpc("ping", id="abc")) == {"jsonrpc": "2.0", "id": "abc", "result": {}}


def test_tools_list_shape():
    server, _ = make_server()
    tools = server.handle(rpc("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["echo", "boom", "api_fail"]
    assert set(tools[0]) == {"name", "title", "description", "inputSchema", "annotations"}
    assert tools[0]["inputSchema"] == ECHO_SCHEMA


def test_tools_call_success_has_text_and_structured_content():
    server, factory = make_server()
    result = call(server, "echo", {"item_id": "MLB000000001"})["result"]
    expected = {"echo": {"item_id": "MLB000000001", "days": 30}, "client": "CLIENT"}
    assert result["structuredContent"] == expected
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == expected
    assert not result.get("isError")
    call(server, "echo", {"item_id": "MLB000000001"})
    assert factory.calls == 1


def test_unknown_tool_is_32602():
    server, _ = make_server()
    err = call(server, "nope", {})["error"]
    assert err["code"] == -32602 and err["message"] == "Unknown tool: nope"


def test_unknown_method_is_32601():
    server, _ = make_server()
    err = server.handle(rpc("foo/bar"))["error"]
    assert err["code"] == -32601 and err["message"] == "Method not found: foo/bar"


def test_missing_required_argument_is_is_error():
    server, _ = make_server()
    result = call(server, "echo", {})["result"]
    assert result["isError"] is True
    assert "missing required argument 'item_id'" in result["content"][0]["text"]


def test_unknown_argument_is_is_error():
    server, _ = make_server()
    result = call(server, "echo", {"item_id": "x", "confirmar": True})["result"]
    assert result["isError"] is True
    assert "unknown argument 'confirmar'" in result["content"][0]["text"]


def test_bool_is_not_integer():
    server, _ = make_server()
    result = call(server, "echo", {"item_id": "x", "days": True})["result"]
    assert result["isError"] is True
    assert "'days' must be an integer" in result["content"][0]["text"]


def test_default_applied():
    server, _ = make_server()
    result = call(server, "echo", {"item_id": "x"})["result"]
    assert result["structuredContent"]["echo"]["days"] == 30


def test_non_object_arguments_is_is_error():
    server, _ = make_server()
    result = call(server, "echo", [1])["result"]
    assert result["isError"] is True
    assert "arguments must be an object" in result["content"][0]["text"]


def test_range_and_length_checks():
    server, _ = make_server()
    for args in ({"item_id": "x", "days": 0}, {"item_id": "x", "days": 91}, {"item_id": ""}):
        assert call(server, "echo", args)["result"]["isError"] is True


def test_tool_exception_is_is_error():
    server, _ = make_server()
    result = call(server, "api_fail")["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Error: GET /x -> 404: nope"


def test_unexpected_exception_logs_to_stderr_not_stdout():
    stderr = io.StringIO()
    server, _ = make_server(stderr)
    result = call(server, "boom")["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Unexpected error (RuntimeError): kaboom"
    assert "Traceback" in stderr.getvalue() and "kaboom" in stderr.getvalue()


def test_notification_returns_none():
    server, _ = make_server()
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_null_id_is_invalid_request():
    server, _ = make_server()
    resp = server.handle({"jsonrpc": "2.0", "id": None, "method": "ping"})
    assert resp["error"]["code"] == -32600 and resp["id"] is None


def test_parse_error_is_32700():
    server, _ = make_server()
    resp = server.handle_line("not json")
    assert resp["error"] == {"code": -32700, "message": "Parse error"}
    assert resp["id"] is None


def test_non_object_is_32600():
    server, _ = make_server()
    for msg in ([1], 5, "x", {"jsonrpc": "2.0", "id": 1}):
        resp = server.handle(msg)
        assert resp["error"] == {"code": -32600, "message": "Invalid Request"}
        assert resp["id"] is None


def test_parse_error_keeps_serving():
    server, _ = make_server()
    ping = json.dumps(rpc("ping", id=7)) + "\n"
    out = io.StringIO()
    server.serve(io.StringIO("not json\n" + ping), out)
    lines = out.getvalue().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["error"]["code"] == -32700
    assert json.loads(lines[1]) == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_serve_skips_blank_lines():
    server, _ = make_server()
    ping = json.dumps(rpc("ping"))
    out = io.StringIO()
    server.serve(io.StringIO(f"\n  \n{ping}\n\n"), out)
    assert len(out.getvalue().splitlines()) == 1


def test_serve_writes_only_json_lines():
    stderr = io.StringIO()
    server, _ = make_server(stderr)
    lines = [
        rpc("initialize", {"protocolVersion": "2025-06-18"}),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        rpc("tools/call", {"name": "boom", "arguments": {}}, id=2),
        rpc("tools/call", {"name": "echo", "arguments": {"item_id": "café"}}, id=3),
    ]
    out = io.StringIO()
    server.serve(io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n"), out)
    parsed = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [p["id"] for p in parsed] == [1, 2, 3]
    assert "café" in out.getvalue()
    assert "Traceback" not in out.getvalue() and "Traceback" in stderr.getvalue()


def test_deeply_nested_line_is_parse_error_and_keeps_serving():
    server, _ = make_server()
    ping = json.dumps(rpc("ping", id=9)) + "\n"
    out = io.StringIO()
    server.serve(io.StringIO("[" * 100000 + "\n" + ping), out)
    lines = out.getvalue().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["error"]["code"] == -32700
    assert json.loads(lines[1]) == {"jsonrpc": "2.0", "id": 9, "result": {}}


def test_handle_never_raises_on_bad_params():
    server, _ = make_server()
    assert call(server, 5)["error"]["code"] == -32602
    resp = server.handle(rpc("tools/call", "str"))
    assert resp["error"]["code"] == -32602
