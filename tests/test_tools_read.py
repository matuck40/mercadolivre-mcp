import pytest

from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS

ITEM_ID = "MLB000000001"


def run(client, name, arguments=None):
    server = Server(TOOLS, lambda: client)
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    return server.handle(message)["result"]


def ok(client, name, arguments=None):
    result = run(client, name, arguments)
    assert not result.get("isError"), result
    return result["structuredContent"]


def raw_item(n, **extra):
    item = {
        "id": f"MLB{n:09d}",
        "title": f"Item {n}",
        "status": "active",
        "price": 10.5,
        "listing_type_id": "gold_special",
        "shipping": {"free_shipping": True},
        "available_quantity": 3,
        "sold_quantity": 2,
        "permalink": f"https://example.test/MLB{n:09d}",
        "category_id": "MLB0001",
        "pictures": [{"id": "pic-1"}, {"id": "pic-2"}],
        "video_id": None,
        "health": 0.9,
        "variations": [],
    }
    item.update(extra)
    return item


def route_search(fake_ml, ids, total=None):
    fake_ml.route(
        "GET",
        "/users/123/items/search",
        body={"results": ids, "paging": {"total": len(ids) if total is None else total}},
    )


def route_multiget(fake_ml):
    def handler(req):
        ids = req.query["ids"][0].split(",")
        return 200, [{"code": 200, "body": raw_item(int(i[3:]))} for i in ids]

    fake_ml.route("GET", "/items", handler=handler)


def test_get_account(fake_ml, client):
    fake_ml.route(
        "GET",
        "/users/me",
        body={
            "id": 123,
            "nickname": "TESTUSER",
            "email": "hidden@example.test",
            "seller_reputation": {
                "level_id": "5_green",
                "power_seller_status": "gold",
                "transactions": {"total": 10},
                "metrics": {"sales": {"completed": 9}},
            },
        },
    )
    assert ok(client, "ml_get_account") == {
        "id": 123,
        "nickname": "TESTUSER",
        "level_id": "5_green",
        "power_seller_status": "gold",
        "transactions": {"total": 10},
        "metrics": {"sales": {"completed": 9}},
    }


def test_list_items_default_args(fake_ml, client):
    route_search(fake_ml, [f"MLB{n:09d}" for n in (1, 2)])
    route_multiget(fake_ml)
    data = ok(client, "ml_list_items")
    query = fake_ml.requests[0].query
    assert query == {"status": ["active"], "limit": ["20"], "offset": ["0"]}
    assert [i["id"] for i in data["items"]] == ["MLB000000001", "MLB000000002"]
    first = data["items"][0]
    assert first["free_shipping"] is True
    assert first["picture_ids"] == ["pic-1", "pic-2"]
    assert first["variations"] == []


def test_list_items_chunks_multiget_by_20(fake_ml, client):
    ids = [f"MLB{n:09d}" for n in range(1, 26)]
    route_search(fake_ml, ids)
    route_multiget(fake_ml)
    data = ok(client, "ml_list_items", {"limit": 50})
    multigets = [r for r in fake_ml.requests if r.path == "/items"]
    assert [len(r.query["ids"][0].split(",")) for r in multigets] == [20, 5]
    assert len(data["items"]) == 25


def test_list_items_pagination_fields(fake_ml, client):
    route_search(fake_ml, ["MLB000000001", "MLB000000002"], total=10)
    route_multiget(fake_ml)
    data = ok(client, "ml_list_items", {"limit": 2, "offset": 4})
    assert (data["total"], data["offset"], data["limit"], data["has_more"]) == (10, 4, 2, True)
    route_search(fake_ml, ["MLB000000001", "MLB000000002"], total=6)
    assert ok(client, "ml_list_items", {"limit": 2, "offset": 4})["has_more"] is False


def test_list_items_skips_failed_multiget_entries(fake_ml, client):
    route_search(fake_ml, ["MLB000000001", "MLB000000002"])
    fake_ml.route(
        "GET",
        "/items",
        body=[{"code": 404, "body": {"message": "gone"}}, {"code": 200, "body": raw_item(2)}],
    )
    data = ok(client, "ml_list_items")
    assert [i["id"] for i in data["items"]] == ["MLB000000002"]


def test_list_items_empty(fake_ml, client):
    route_search(fake_ml, [])
    data = ok(client, "ml_list_items")
    assert data == {"items": [], "total": 0, "offset": 0, "limit": 20, "has_more": False}
    assert not [r for r in fake_ml.requests if r.path == "/items"]


def test_list_items_rejects_bad_status(fake_ml, client):
    result = run(client, "ml_list_items", {"status": "deleted"})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_get_item_includes_attributes_and_description(fake_ml, client):
    item = raw_item(
        1,
        attributes=[{"id": "BRAND", "name": "Brand", "value_name": "Acme", "extra": 1}],
        variations=[
            {
                "id": 77,
                "attribute_combinations": [
                    {"value_name": "Red"},
                    {"value_name": "Large"},
                ],
                "available_quantity": 1,
                "sold_quantity": 4,
                "picture_ids": ["pic-1"],
                "attributes": [
                    {"id": "COLOR", "value_name": "Red"},
                    {"id": "SELLER_SKU", "value_name": "SKU-1"},
                ],
            },
            {
                "id": 78,
                "attribute_combinations": [{"value_name": "Blue"}],
                "seller_custom_field": "ONLY-CUSTOM",
            },
        ],
    )
    fake_ml.route("GET", f"/items/{ITEM_ID}", body=item)
    fake_ml.route("GET", f"/items/{ITEM_ID}/description", body={"plain_text": "Hello"})
    data = ok(client, "ml_get_item", {"item_id": ITEM_ID})
    assert data["attributes"] == [{"id": "BRAND", "name": "Brand", "value_name": "Acme"}]
    assert data["description"] == "Hello"
    assert data["variations"] == [
        {
            "id": 77,
            "combination": "Red, Large",
            "available_quantity": 1,
            "sold_quantity": 4,
            "picture_ids": ["pic-1"],
            "seller_sku": "SKU-1",
        },
        {
            "id": 78,
            "combination": "Blue",
            "available_quantity": None,
            "sold_quantity": None,
            "picture_ids": [],
            "seller_sku": None,
        },
    ]


def test_get_item_description_missing_is_none(fake_ml, client):
    fake_ml.route("GET", f"/items/{ITEM_ID}", body=raw_item(1))
    fake_ml.route("GET", f"/items/{ITEM_ID}/description", status=404, body={"message": "none"})
    data = ok(client, "ml_get_item", {"item_id": ITEM_ID})
    assert data["description"] is None
    assert data["attributes"] == []


def test_get_item_visits_default_30_days(fake_ml, client):
    fake_ml.route(
        "GET",
        f"/items/{ITEM_ID}/visits/time_window",
        body={
            "total_visits": 7,
            "results": [
                {"date": "2026-10-01T00:00:00Z", "total": 3},
                {"date": "2026-10-02T00:00:00Z", "total": 4},
            ],
        },
    )
    data = ok(client, "ml_get_item_visits", {"item_id": ITEM_ID})
    assert fake_ml.requests[0].query == {"last": ["30"], "unit": ["day"]}
    assert data == {
        "item_id": ITEM_ID,
        "days": 30,
        "total": 7,
        "per_day": [
            {"date": "2026-10-01", "visits": 3},
            {"date": "2026-10-02", "visits": 4},
        ],
    }


@pytest.mark.parametrize("days", [0, 151])
def test_get_item_visits_days_out_of_range_is_is_error(fake_ml, client, days):
    result = run(client, "ml_get_item_visits", {"item_id": ITEM_ID, "days": days})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_read_tools_are_annotated_read_only():
    for name in ("ml_get_account", "ml_list_items", "ml_get_item", "ml_get_item_visits"):
        tool = TOOLS[name]
        assert tool.annotations == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
        assert tool.input_schema["additionalProperties"] is False
