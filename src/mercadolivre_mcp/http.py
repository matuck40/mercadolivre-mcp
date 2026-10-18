"""One urllib call with JSON, form and raw bodies. Redirects are never followed."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from .errors import MLError

_MAX_TEXT = 500


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the bearer token is never re-sent to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _parse(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text[:_MAX_TEXT]


def request(
    method: str,
    url: str,
    *,
    json_body: Any = None,
    form: Mapping[str, str] | None = None,
    raw: bytes | None = None,
    content_type: str | None = None,
    token: str | None = None,
    timeout: float = 60,
) -> tuple[int, Any]:
    """Send one HTTP request and return ``(status, parsed_body)``.

    HTTP error statuses (including 3xx, which are never followed) are returned,
    not raised. Network failures raise ``MLError``.
    """
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif raw is not None:
        data = raw
        if content_type:
            headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 - scheme is checked by callers
    try:
        with _opener.open(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, _parse(resp.read())
    except urllib.error.HTTPError as err:
        try:
            return err.code, _parse(err.read())
        finally:
            err.close()
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        reason = getattr(err, "reason", err)
        target = urllib.parse.urlsplit(url)._replace(query="", fragment="").geturl()
        raise MLError(f"Network error calling {method} {target}: {reason}") from err
