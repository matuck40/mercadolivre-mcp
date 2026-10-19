from datetime import datetime, timedelta, timezone

import pytest

from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS
from mercadolivre_mcp.tools.read import orders_since

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
    for name in (
        "ml_get_account",
        "ml_list_items",
        "ml_get_item",
        "ml_get_item_visits",
        "ml_list_questions",
        "ml_list_orders",
        "ml_api_get",
    ):
        tool = TOOLS[name]
        assert tool.annotations == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }
        assert tool.input_schema["additionalProperties"] is False


def raw_question(n, answered=False):
    return {
        "id": n,
        "item_id": ITEM_ID,
        "date_created": "2026-10-01T10:00:00.000-03:00",
        "text": f"Question {n}?",
        "status": "ANSWERED" if answered else "UNANSWERED",
        "answer": {"text": "Yes", "extra": 1} if answered else None,
        "from": {"id": 999},
    }


def test_list_questions_default(fake_ml, client):
    fake_ml.route(
        "GET",
        "/questions/search",
        body={"questions": [raw_question(1), raw_question(2, answered=True)], "total": 5},
    )
    data = ok(client, "ml_list_questions")
    assert fake_ml.requests[0].query == {
        "seller_id": ["123"],
        "status": ["UNANSWERED"],
        "api_version": ["4"],
        "limit": ["20"],
        "offset": ["0"],
    }
    assert data["questions"] == [
        {
            "id": 1,
            "item_id": ITEM_ID,
            "date_created": "2026-10-01T10:00:00.000-03:00",
            "text": "Question 1?",
            "status": "UNANSWERED",
            "answer": None,
        },
        {
            "id": 2,
            "item_id": ITEM_ID,
            "date_created": "2026-10-01T10:00:00.000-03:00",
            "text": "Question 2?",
            "status": "ANSWERED",
            "answer": "Yes",
        },
    ]
    assert (data["total"], data["offset"], data["limit"], data["has_more"]) == (5, 0, 20, True)


def test_list_questions_total_falls_back_to_paging(fake_ml, client):
    fake_ml.route(
        "GET",
        "/questions/search",
        body={"questions": [raw_question(1)], "paging": {"total": 1}},
    )
    data = ok(client, "ml_list_questions")
    assert (data["total"], data["has_more"]) == (1, False)


def test_list_questions_filters_item(fake_ml, client):
    fake_ml.route("GET", "/questions/search", body={"questions": [], "total": 0})
    ok(client, "ml_list_questions", {"status": "ANSWERED", "item_id": ITEM_ID, "limit": 5})
    query = fake_ml.requests[0].query
    assert query["item"] == [ITEM_ID]
    assert query["status"] == ["ANSWERED"]
    assert query["limit"] == ["5"]


def test_list_questions_rejects_bad_status(fake_ml, client):
    result = run(client, "ml_list_questions", {"status": "DELETED"})
    assert result["isError"] is True
    assert fake_ml.requests == []


@pytest.mark.parametrize(("offset_hours", "suffix"), [(-3, "-03:00"), (9, "+09:00"), (0, "+00:00")])
def test_orders_since_uses_local_offset(offset_hours, suffix):
    now = datetime(2026, 5, 10, 15, 0, tzinfo=timezone(timedelta(hours=offset_hours)))
    assert orders_since(1, now) == f"2026-05-09T00:00:00.000{suffix}"


def test_orders_since_defaults_to_machine_clock():
    value = orders_since(30)
    offset = datetime.now().astimezone().strftime("%z")
    assert value.endswith(f"{offset[:3]}:{offset[3:]}")
    assert value[10:23] == "T00:00:00.000"


def raw_order(order_id, items):
    return {
        "id": order_id,
        "date_created": "2026-10-02T09:00:00.000-03:00",
        "status": "paid",
        "total_amount": 55.0,
        "buyer": {"id": 1},
        "order_items": items,
    }


def raw_order_item(item_id, title, variation_attributes=None):
    return {
        "item": {
            "id": item_id,
            "title": title,
            "variation_attributes": variation_attributes or [],
        },
        "quantity": 2,
        "unit_price": 20.0,
        "sale_fee": 3.5,
    }


def test_list_orders_flattens_order_items(fake_ml, client):
    fake_ml.route(
        "GET",
        "/orders/search",
        body={
            "results": [
                raw_order(
                    900,
                    [
                        raw_order_item(
                            ITEM_ID,
                            "Item 1",
                            [{"value_name": "Red"}, {"value_name": "Large"}],
                        ),
                        raw_order_item("MLB000000002", "Item 2"),
                    ],
                ),
                raw_order(901, [raw_order_item("MLB000000003", "Item 3")]),
            ],
            "paging": {"total": 2},
        },
    )
    data = ok(client, "ml_list_orders", {"days": 7})
    query = fake_ml.requests[0].query
    assert query["seller"] == ["123"]
    assert query["sort"] == ["date_desc"]
    assert (query["limit"], query["offset"]) == (["50"], ["0"])
    offset = datetime.now().astimezone().strftime("%z")
    assert query["order.date_created.from"][0].endswith(f"{offset[:3]}:{offset[3:]}")
    assert data["days"] == 7
    assert len(data["orders"]) == 3
    assert data["orders"][0] == {
        "order_id": 900,
        "date_created": "2026-10-02T09:00:00.000-03:00",
        "status": "paid",
        "item_id": ITEM_ID,
        "title": "Item 1",
        "variation": "Red, Large",
        "quantity": 2,
        "unit_price": 20.0,
        "sale_fee": 3.5,
        "total_amount": 55.0,
    }
    assert data["orders"][1]["variation"] == ""
    assert data["orders"][2]["order_id"] == 901
    assert (data["total"], data["offset"], data["limit"], data["has_more"]) == (2, 0, 50, False)


def test_list_orders_has_more_counts_orders_not_rows(fake_ml, client):
    items = [raw_order_item(ITEM_ID, "A"), raw_order_item("MLB000000002", "B")]
    fake_ml.route(
        "GET",
        "/orders/search",
        body={"results": [raw_order(900, items)], "paging": {"total": 3}},
    )
    data = ok(client, "ml_list_orders", {"limit": 1, "offset": 0})
    assert len(data["orders"]) == 2
    assert data["has_more"] is True


@pytest.mark.parametrize("days", [0, 366])
def test_list_orders_days_out_of_range_is_is_error(fake_ml, client, days):
    result = run(client, "ml_list_orders", {"days": days})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_api_get_adds_leading_slash(fake_ml, client):
    fake_ml.route("GET", "/categories/MLB1234", body={"id": "MLB1234"})
    data = ok(client, "ml_api_get", {"path": "categories/MLB1234"})
    assert data == {"path": "/categories/MLB1234", "response": {"id": "MLB1234"}}
    assert fake_ml.requests[0].path == "/categories/MLB1234"


def test_api_get_keeps_existing_slash(fake_ml, client):
    fake_ml.route("GET", "/categories/MLB1234", body={"id": "MLB1234"})
    data = ok(client, "ml_api_get", {"path": "/categories/MLB1234"})
    assert data["path"] == "/categories/MLB1234"


@pytest.mark.parametrize("path", ["https://evil.test/x", "//evil.test/x"])
def test_api_get_rejects_absolute_url(fake_ml, fake_other_host, client, path):
    result = run(client, "ml_api_get", {"path": path})
    assert result["isError"] is True
    assert fake_ml.requests == []
    assert fake_other_host.requests == []


@pytest.mark.parametrize("path", ["/users/me\r\nX-Evil: 1", "/users/me\x00", "/a b"])
def test_api_get_rejects_control_chars(fake_ml, client, path):
    result = run(client, "ml_api_get", {"path": path})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_api_get_only_uses_get(fake_ml, client):
    fake_ml.route("GET", "/users/me", body={"id": 123})
    ok(client, "ml_api_get", {"path": "/users/me"})
    assert fake_ml.writes() == []
    assert [r.method for r in fake_ml.requests] == ["GET"]
