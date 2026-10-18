"""Write tools: picture upload (item updates and answers are added later)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from ..errors import ToolInputError
from .read import _schema
from .registry import Tool

if TYPE_CHECKING:
    from ..client import MLClient

WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}

MAX_PICTURE_BYTES = 10 * 1024 * 1024


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


WRITE_TOOLS = [
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
]
