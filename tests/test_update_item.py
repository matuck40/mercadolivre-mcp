from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS
from mercadolivre_mcp.tools.write import build_update_request, merge_variations

ITEM = {"id": "MLB000000001", "title": "Item", "price": 50, "status": "active"}
ITEM_WITH_VARIATIONS = {**ITEM, "variations": [{"id": 1}, {"id": 2}, {"id": 3}]}


def run(client, arguments):
    server = Server(TOOLS, lambda: client)
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "ml_update_item", "arguments": arguments},
    }
    return server.handle(message)["result"]


def route_item(fake_ml, item=ITEM):
    fake_ml.route("GET", "/items/MLB000000001", body=item)
    fake_ml.route("PUT", "/items/MLB000000001", body={**item, "price": 59.9})


def test_preview_makes_no_write_request(client, fake_ml):
    route_item(fake_ml)
    result = run(client, {"item_id": "MLB000000001", "fields": {"price": 59.9}})
    assert not result.get("isError"), result
    out = result["structuredContent"]
    assert fake_ml.writes() == []
    assert out["preview"] is True
    assert out["before"] == {"price": 50}
    assert out["after"] == {"price": 59.9}
    assert out["request"] == {
        "method": "PUT",
        "path": "/items/MLB000000001",
        "body": {"price": 59.9},
    }
    assert out["notice"] == (
        "Nothing was changed. Show this preview to the user and call again "
        "with confirm=true only after they approve it."
    )


def test_confirm_sends_put_with_fields(client, fake_ml):
    route_item(fake_ml)
    result = run(client, {"item_id": "MLB000000001", "fields": {"price": 59.9}, "confirm": True})
    assert not result.get("isError"), result
    out = result["structuredContent"]
    (req,) = fake_ml.writes()
    assert req.method == "PUT"
    assert req.path == "/items/MLB000000001"
    assert req.json == {"price": 59.9}
    assert out["preview"] is False
    assert out["item_id"] == "MLB000000001"
    assert out["result"]["price"] == 59.9


def test_confirm_request_equals_preview_request(client, fake_ml):
    route_item(fake_ml, ITEM_WITH_VARIATIONS)
    args = {
        "item_id": "MLB000000001",
        "fields": {"price": 59.9, "variations": [{"id": 2, "available_quantity": 5}]},
    }
    preview = run(client, args)["structuredContent"]
    run(client, {**args, "confirm": True})
    (req,) = fake_ml.writes()
    assert req.json == preview["request"]["body"]
    assert req.path == preview["request"]["path"]


def test_variations_merge_keeps_unlisted_variations(client, fake_ml):
    route_item(fake_ml, ITEM_WITH_VARIATIONS)
    run(
        client,
        {
            "item_id": "MLB000000001",
            "fields": {"variations": [{"id": 2, "available_quantity": 5}]},
            "confirm": True,
        },
    )
    (req,) = fake_ml.writes()
    variations = req.json["variations"]
    assert [v["id"] for v in variations] == [2, 1, 3]
    assert variations[0] == {"id": 2, "available_quantity": 5}
    assert variations[1] == {"id": 1}
    assert variations[2] == {"id": 3}


def test_preview_shows_merged_variations(client, fake_ml):
    route_item(fake_ml, ITEM_WITH_VARIATIONS)
    out = run(
        client,
        {
            "item_id": "MLB000000001",
            "fields": {"variations": [{"id": 2, "available_quantity": 5}]},
        },
    )["structuredContent"]
    assert [v["id"] for v in out["after"]["variations"]] == [2, 1, 3]
    assert out["request"]["body"] == out["after"]
    assert out["before"] == {"variations": [{"id": 1}, {"id": 2}, {"id": 3}]}


def test_new_variation_without_id_is_kept(client, fake_ml):
    route_item(fake_ml, ITEM_WITH_VARIATIONS)
    new = {"price": 10, "available_quantity": 1}
    run(client, {"item_id": "MLB000000001", "fields": {"variations": [new]}, "confirm": True})
    (req,) = fake_ml.writes()
    assert req.json["variations"] == [new, {"id": 1}, {"id": 2}, {"id": 3}]


def test_confirm_false_explicit_is_preview(client, fake_ml):
    route_item(fake_ml)
    out = run(client, {"item_id": "MLB000000001", "fields": {"price": 59.9}, "confirm": False})[
        "structuredContent"
    ]
    assert out["preview"] is True
    assert fake_ml.writes() == []


def test_confirm_must_be_boolean(client, fake_ml):
    route_item(fake_ml)
    result = run(client, {"item_id": "MLB000000001", "fields": {"price": 59.9}, "confirm": "true"})
    assert result["isError"] is True
    assert fake_ml.writes() == []


def test_empty_fields_is_is_error(client, fake_ml):
    route_item(fake_ml)
    result = run(client, {"item_id": "MLB000000001", "fields": {}})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_variations_must_be_a_list(client, fake_ml):
    route_item(fake_ml)
    result = run(
        client,
        {"item_id": "MLB000000001", "fields": {"variations": "x"}, "confirm": True},
    )
    assert result["isError"] is True
    assert fake_ml.writes() == []


def test_put_error_is_is_error(client, fake_ml):
    fake_ml.route("GET", "/items/MLB000000001", body=ITEM)
    fake_ml.route("PUT", "/items/MLB000000001", status=400, body={"message": "bad price"})
    result = run(client, {"item_id": "MLB000000001", "fields": {"price": -1}, "confirm": True})
    assert result["isError"] is True
    assert "bad price" in result["content"][0]["text"]


def test_merge_and_build_helpers():
    merged = merge_variations([{"id": 1}, {"id": 2}], [{"id": 2, "x": 1}])
    assert merged == [{"id": 2, "x": 1}, {"id": 1}]
    request = build_update_request({"id": "MLB000000001"}, {"price": 1})
    assert request == {"method": "PUT", "path": "/items/MLB000000001", "body": {"price": 1}}


def test_tool_order_and_description():
    names = list(TOOLS)
    assert names.index("ml_update_item") < names.index("ml_upload_picture")
    tool = TOOLS["ml_update_item"]
    assert "confirm=true" in tool.description
    assert tool.annotations["destructiveHint"] is True
    assert tool.annotations["idempotentHint"] is True
