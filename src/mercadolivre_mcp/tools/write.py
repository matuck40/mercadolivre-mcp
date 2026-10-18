"""Write tools: item updates (preview and confirm) and picture upload."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from ..errors import ToolInputError
from .read import ITEM_ID_PROP, _schema, summarize_item
from .registry import Tool

if TYPE_CHECKING:
    from ..client import MLClient

WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}

UPDATE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

MAX_PICTURE_BYTES = 10 * 1024 * 1024


def merge_variations(current: list[dict], requested: list[dict]) -> list[dict]:
    """Complete a partial variations list so Mercado Livre does not delete the others.

    Requested entries keep their order and content (entries without ``id`` are new
    variations); every current variation id not mentioned is appended as ``{"id": id}``.
    """
    mentioned = {v.get("id") for v in requested if v.get("id") is not None}
    merged = [dict(v) for v in requested]
    for variation in current:
        vid = variation.get("id")
        if vid is not None and vid not in mentioned:
            merged.append({"id": vid})
    return merged


def build_update_request(current_item: dict, fields: dict) -> dict:
    """The exact PUT for ``fields`` against the item in its current state."""
    body = dict(fields)
    if "variations" in fields:
        body["variations"] = merge_variations(
            current_item.get("variations") or [], fields["variations"]
        )
    path = f"/items/{quote(str(current_item['id']), safe='')}"
    return {"method": "PUT", "path": path, "body": body}


def update_item(client: MLClient, args: dict) -> dict:
    item_id = args["item_id"]
    fields = args["fields"]
    if not fields:
        raise ToolInputError("fields must contain at least one field to change")
    if "variations" in fields and not isinstance(fields["variations"], list):
        raise ToolInputError("fields.variations must be a list of variation objects")
    current = client.get(f"/items/{quote(item_id, safe='')}")
    request = build_update_request({**current, "id": item_id}, fields)
    if not args.get("confirm", False):
        return {
            "preview": True,
            "item_id": item_id,
            "request": request,
            "before": {k: current.get(k) for k in fields},
            "after": request["body"],
            "notice": (
                "Nothing was changed. Show this preview to the user and call again "
                "with confirm=true only after they approve it."
            ),
        }
    response = client.put(request["path"], request["body"])
    return {
        "preview": False,
        "item_id": item_id,
        "request": request,
        "result": summarize_item(response),
    }


def _image_type(head: bytes) -> str | None:
    """Content type from the leading bytes, or None when not JPEG/PNG/WEBP."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _read_picture(file_path: str) -> tuple[Path, bytes, str]:
    """Apply the upload guard and return (path, bytes, content type).

    Order: absolute path, regular file, size, magic bytes. Messages never echo
    file contents.
    """
    path = Path(file_path)
    if not path.is_absolute():
        raise ToolInputError("file_path must be an absolute path")
    try:
        mode = os.stat(path).st_mode
    except OSError as exc:
        raise ToolInputError(
            f"file_path cannot be read ({exc.strerror or 'unknown error'}); "
            "pass the absolute path of an existing image file"
        ) from exc
    if not stat.S_ISREG(mode):
        raise ToolInputError("file_path must be a regular file, not a directory or device")
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_PICTURE_BYTES + 1)
    except OSError as exc:
        raise ToolInputError(
            f"file_path cannot be read ({exc.strerror or 'unknown error'})"
        ) from exc
    if len(data) > MAX_PICTURE_BYTES:
        raise ToolInputError("file is larger than 10 MB; resize or compress the picture first")
    content_type = _image_type(data[:12])
    if content_type is None:
        raise ToolInputError(
            "file is not a JPEG, PNG or WEBP image (checked the file header, not the extension); "
            "only real image files can be uploaded"
        )
    return path, data, content_type


def upload_picture(client: MLClient, args: dict) -> dict:
    path, data, content_type = _read_picture(args["file_path"])
    resp = client.upload("/pictures/items/upload", data, path.name, content_type)
    return {
        "picture_id": resp["id"],
        "max_size": resp.get("max_size"),
        "next_step": (
            "Use this picture_id in `pictures` or in `variations[].picture_ids` of "
            "ml_update_item (call it without confirm first to preview the change)."
        ),
    }


def answer_question(client: MLClient, args: dict) -> dict:
    question_id = args["question_id"]
    text = args["text"]
    if not text.strip():
        raise ToolInputError("text must contain more than whitespace")
    question = client.get(f"/questions/{question_id}?api_version=4")
    request = {
        "method": "POST",
        "path": "/answers",
        "body": {"question_id": question_id, "text": text},
    }
    if not args.get("confirm", False):
        return {
            "preview": True,
            "question_id": question_id,
            "request": request,
            "before": {
                "question": question.get("text"),
                "status": question.get("status"),
                "existing_answer": (question.get("answer") or {}).get("text"),
            },
            "after": {"answer": text},
            "notice": (
                "Nothing was sent. Show this preview to the user and call again "
                "with confirm=true only after they approve it."
            ),
        }
    response = client.post(request["path"], request["body"])
    return {
        "preview": False,
        "question_id": question_id,
        "request": request,
        "result": response,
    }


WRITE_TOOLS = [
    Tool(
        name="ml_update_item",
        title="Update item",
        description=(
            "Change fields of one of your Mercado Livre items (price, stock, title, status, "
            "pictures, variations, ...). Nothing is changed unless confirm=true. Call it "
            "without confirm first to get a preview (before, after and the exact request), "
            "show that preview to the user, and call again with confirm=true only after "
            "their explicit approval. Partial `variations` are completed with the ids of "
            "the item's other variations, because Mercado Livre deletes any variation "
            "missing from the request."
        ),
        input_schema=_schema(
            {
                "item_id": ITEM_ID_PROP,
                "fields": {
                    "type": "object",
                    "minProperties": 1,
                    "description": (
                        'Fields to change, sent as the PUT body, for example {"price": 59.9}.'
                    ),
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "false (default) returns a preview and changes nothing; "
                        "true applies the change."
                    ),
                },
            },
            required=["item_id", "fields"],
        ),
        annotations=UPDATE,
        handler=update_item,
    ),
    Tool(
        name="ml_upload_picture",
        title="Upload picture",
        description=(
            "Upload a local image to Mercado Livre and return its picture id. Only real "
            "JPEG, PNG or WEBP files up to 10 MB are accepted, given by absolute path; "
            "anything else is refused. The picture is not attached to any item until you "
            "use the id with ml_update_item."
        ),
        input_schema=_schema(
            {
                "file_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Absolute path of a JPEG, PNG or WEBP file (max 10 MB).",
                }
            },
            required=["file_path"],
        ),
        annotations=WRITE,
        handler=upload_picture,
    ),
    Tool(
        name="ml_answer_question",
        title="Answer question",
        description=(
            "Answer a buyer question on one of your Mercado Livre listings. The answer is "
            "public on the listing. Nothing is sent unless confirm=true. Call it without "
            "confirm first to get a preview (the question and the exact request), show that "
            "preview to the user, and call again with confirm=true only after their "
            "explicit approval."
        ),
        input_schema=_schema(
            {
                "question_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Id of the question to answer (see ml_list_questions).",
                },
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000,
                    "description": "The answer text (max 2000 characters).",
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "false (default) returns a preview and sends nothing; "
                        "true posts the answer."
                    ),
                },
            },
            required=["question_id", "text"],
        ),
        annotations=WRITE,
        handler=answer_question,
    ),
]
