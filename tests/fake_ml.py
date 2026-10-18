"""A local HTTP test double for the Mercado Livre API.

Binds to 127.0.0.1 on an ephemeral port, records every request and answers from
routes registered with ``route``. Unrouted paths get a 404 JSON body.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlsplit


class Headers(dict[str, str]):
    """Dict with case-insensitive lookups; original key spelling is kept."""

    def _find(self, key: object) -> str | None:
        if isinstance(key, str):
            lowered = key.lower()
            for existing in dict.keys(self):
                if existing.lower() == lowered:
                    return existing
        return None

    def __getitem__(self, key: str) -> str:
        found = self._find(key)
        return super().__getitem__(key if found is None else found)

    def __contains__(self, key: object) -> bool:
        return self._find(key) is not None

    def get(self, key: str, default: Any = None) -> Any:
        found = self._find(key)
        return default if found is None else super().__getitem__(found)


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: Headers
    body: bytes

    @property
    def json(self) -> Any:
        """Parsed JSON body, or None if the body is empty or not JSON."""
        if not self.body:
            return None
        try:
            return json.loads(self.body)
        except ValueError:
            return None

    @property
    def form(self) -> dict[str, str]:
        """Body parsed as application/x-www-form-urlencoded."""
        return dict(parse_qsl(self.body.decode("utf-8", errors="replace")))


Handler = Callable[[RecordedRequest], tuple[int, Any] | tuple[int, Any, dict[str, str]]]


@dataclass
class _Route:
    status: int
    body: Any
    handler: Handler | None
    headers: dict[str, str] | None


class FakeML:
    def __init__(self, advertised_host: str = "127.0.0.1") -> None:
        self._advertised_host = advertised_host
        self._routes: dict[tuple[str, str], _Route] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.requests: list[RecordedRequest] = []
        self.url = ""

    def route(
        self,
        method: str,
        path: str,
        status: int = 200,
        body: Any = None,
        handler: Handler | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._routes[(method.upper(), path)] = _Route(status, body, handler, headers)

    def writes(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.method != "GET"]

    def start(self) -> None:
        fake = self

        class _Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                recorded = RecordedRequest(
                    method=self.command,
                    path=parts.path,
                    query=parse_qs(parts.query),
                    headers=Headers(self.headers.items()),
                    body=self.rfile.read(length) if length else b"",
                )
                fake.requests.append(recorded)
                route = fake._routes.get((self.command, parts.path))
                extra: dict[str, str] = {}
                if route is None:
                    status, payload = 404, {"message": "not found"}
                elif route.handler is not None:
                    try:
                        result = route.handler(recorded)
                        status, payload = result[0], result[1]
                        if len(result) > 2:
                            extra = result[2]
                    except Exception as exc:  # noqa: BLE001
                        status, payload = 500, {"message": f"{type(exc).__name__}: {exc}"}
                else:
                    status, payload = route.status, route.body
                    extra = route.headers or {}
                if isinstance(payload, bytes):
                    data, ctype = payload, "application/octet-stream"
                elif isinstance(payload, str):
                    data, ctype = payload.encode(), "text/plain"
                else:
                    data, ctype = json.dumps(payload).encode(), "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for name, value in extra.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _serve  # noqa: N815

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                """Silence the default request logging."""

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        port = self._server.server_address[1]
        self.url = f"http://{self._advertised_host}:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
