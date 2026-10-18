"""Authenticated Mercado Livre API client with a URL guard and one 401 retry."""

from __future__ import annotations

import secrets
from typing import Any

from .auth import TokenStore, access_token
from .config import Config
from .errors import APIError, AuthError, ToolInputError
from .http import request

_PATH_HINT = "Path must be a relative API path such as /items/MLB000000001"


class MLClient:
    def __init__(self, config: Config, store: TokenStore | None = None):
        self.config = config
        self.store = store if store is not None else TokenStore(config.secrets_dir)

    def _url(self, path: str) -> str:
        """Build the request URL; always ``api_base + path`` so the token stays on the API host."""
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "://" in path
            or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in path)
        ):
            raise ToolInputError(_PATH_HINT)
        return self.config.api_base + path

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self._url(path)
        shown = path.split("?", 1)[0]
        status, body = 0, None
        for attempt in range(2):
            token = access_token(self.config, self.store, force_refresh=attempt == 1)
            status, body = request(method, url, token=token, **kwargs)
            if status != 401:
                break
        else:
            raise AuthError(
                "Mercado Livre rejected the token (401). "
                "Run `mercadolivre-mcp auth url` to authorize again."
            )
        if status >= 300:
            raise APIError(method, shown, status, body)
        return body

    def get(self, path: str) -> Any:
        return self._send("GET", path)

    def put(self, path: str, body: Any) -> Any:
        return self._send("PUT", path, json_body=body)

    def post(self, path: str, body: Any) -> Any:
        return self._send("POST", path, json_body=body)

    def upload(self, path: str, data: bytes, filename: str, content_type: str) -> Any:
        boundary = secrets.token_hex(16)
        filename = filename.translate({ord('"'): "_", ord("\r"): "_", ord("\n"): "_"})
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        payload = head + data + f"\r\n--{boundary}--\r\n".encode()
        return self._send(
            "POST",
            path,
            raw=payload,
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def user_id(self) -> int:
        stored = self.store.load().get("user_id")
        if stored is not None:
            return int(stored)
        return int(self.get("/users/me")["id"])
