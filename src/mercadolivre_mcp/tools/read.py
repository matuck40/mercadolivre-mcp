"""Read-only tools: account, item listing, item detail and item visits."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode

from ..errors import APIError
from .registry import Tool

if TYPE_CHECKING:
    from ..client import MLClient

READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

MULTIGET_CHUNK = 20


def _schema(properties: dict | None = None, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    return schema


ITEM_ID_PROP = {
    "type": "string",
    "minLength": 1,
    "description": "Item id, for example MLB000000001.",
}


def _variation_summary(variation: dict) -> dict:
    combos = variation.get("attribute_combinations") or []
    return {
        "id": variation.get("id"),
        "combination": ", ".join(str(c.get("value_name")) for c in combos),
        "available_quantity": variation.get("available_quantity"),
        "sold_quantity": variation.get("sold_quantity"),
        "picture_ids": variation.get("picture_ids") or [],
        "seller_sku": next(
            (
                a.get("value_name")
                for a in variation.get("attributes") or []
                if a.get("id") == "SELLER_SKU"
            ),
            None,
        ),
    }


def summarize_item(item: dict) -> dict:
    """Reduce a raw item payload to the fields the tools expose."""
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "status": item.get("status"),
        "price": item.get("price"),
        "listing_type_id": item.get("listing_type_id"),
        "free_shipping": (item.get("shipping") or {}).get("free_shipping"),
        "available_quantity": item.get("available_quantity"),
        "sold_quantity": item.get("sold_quantity"),
        "permalink": item.get("permalink"),
        "category_id": item.get("category_id"),
        "picture_ids": [p.get("id") for p in item.get("pictures") or []],
        "video_id": item.get("video_id"),
        "health": item.get("health"),
        "variations": [_variation_summary(v) for v in item.get("variations") or []],
    }


def get_account(client: MLClient, args: dict) -> dict:
    me = client.get("/users/me")
    reputation = me.get("seller_reputation") or {}
    return {
        "id": me.get("id"),
        "nickname": me.get("nickname"),
        "level_id": reputation.get("level_id"),
        "power_seller_status": reputation.get("power_seller_status"),
        "transactions": reputation.get("transactions"),
        "metrics": reputation.get("metrics"),
    }


def list_items(client: MLClient, args: dict) -> dict:
    status = args.get("status", "active")
    limit = args.get("limit", 20)
    offset = args.get("offset", 0)
    query = urlencode({"status": status, "limit": limit, "offset": offset})
    found = client.get(f"/users/{client.user_id()}/items/search?{query}")
    ids = found.get("results") or []
    total = (found.get("paging") or {}).get("total", len(ids))
    items = []
    for start in range(0, len(ids), MULTIGET_CHUNK):
        chunk = ",".join(ids[start : start + MULTIGET_CHUNK])
        for entry in client.get(f"/items?ids={chunk}"):
            if entry.get("code") == 200:
                items.append(summarize_item(entry["body"]))
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(ids) < total,
    }


def get_item(client: MLClient, args: dict) -> dict:
    item_id = quote(args["item_id"], safe="")
    item = client.get(f"/items/{item_id}")
    result = summarize_item(item)
    result["attributes"] = [
        {"id": a.get("id"), "name": a.get("name"), "value_name": a.get("value_name")}
        for a in item.get("attributes") or []
    ]
    try:
        result["description"] = client.get(f"/items/{item_id}/description").get("plain_text")
    except APIError:
        result["description"] = None
    return result


def get_item_visits(client: MLClient, args: dict) -> dict:
    item_id = args["item_id"]
    days = args.get("days", 30)
    data = client.get(f"/items/{quote(item_id, safe='')}/visits/time_window?last={days}&unit=day")
    return {
        "item_id": item_id,
        "days": days,
        "total": data.get("total_visits"),
        "per_day": [
            {"date": str(r.get("date"))[:10], "visits": r.get("total")}
            for r in data.get("results") or []
        ],
    }


READ_TOOLS = [
    Tool(
        name="ml_get_account",
        title="Get seller account",
        description=(
            "Read-only. Return the authenticated seller's id, nickname, reputation level, "
            "power seller status, transaction counts and metrics."
        ),
        input_schema=_schema(),
        annotations=READ_ONLY,
        handler=get_account,
    ),
    Tool(
        name="ml_list_items",
        title="List items",
        description=(
            "Read-only. List the seller's items by status with a short summary of each "
            "(price, stock, sales, pictures, variations). Paginated with limit and offset."
        ),
        input_schema=_schema(
            {
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "closed"],
                    "default": "active",
                    "description": "Item status to list.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                    "description": "Page size.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Number of items to skip.",
                },
            }
        ),
        annotations=READ_ONLY,
        handler=list_items,
    ),
    Tool(
        name="ml_get_item",
        title="Get item",
        description=(
            "Read-only. Return one item with its summary, attributes and plain-text "
            "description (null when the item has no description)."
        ),
        input_schema=_schema({"item_id": ITEM_ID_PROP}, required=["item_id"]),
        annotations=READ_ONLY,
        handler=get_item,
    ),
    Tool(
        name="ml_get_item_visits",
        title="Get item visits",
        description="Read-only. Return daily visit counts for an item over the last N days.",
        input_schema=_schema(
            {
                "item_id": ITEM_ID_PROP,
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 150,
                    "default": 30,
                    "description": "Number of days to look back.",
                },
            },
            required=["item_id"],
        ),
        annotations=READ_ONLY,
        handler=get_item_visits,
    ),
]
