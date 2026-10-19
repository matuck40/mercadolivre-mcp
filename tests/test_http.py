"""Tests for the urllib HTTP helper."""

from __future__ import annotations

import socket

import pytest
from fake_ml import FakeML

from mercadolivre_mcp.errors import MLError
from mercadolivre_mcp.http import request


def test_get_parses_json(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/x", body={"a": 1})
    status, body = request("GET", fake_ml.url + "/x")
    assert (status, body) == (200, {"a": 1})
    assert fake_ml.requests[0].headers["Accept"] == "application/json"


def test_json_body_and_content_type(fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/x", body={"ok": True})
    request("POST", fake_ml.url + "/x", json_body={"k": "v"})
    sent = fake_ml.requests[0]
    assert sent.json == {"k": "v"}
    assert sent.headers["Content-Type"] == "application/json"


def test_form_body_is_urlencoded(fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/x", body={})
    request("POST", fake_ml.url + "/x", form={"a": "b c", "d": "e&f"})
    sent = fake_ml.requests[0]
    assert sent.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert sent.form == {"a": "b c", "d": "e&f"}


def test_raw_body_with_content_type(fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/x", body={})
    request("POST", fake_ml.url + "/x", raw=b"\x00\x01data", content_type="image/png")
    sent = fake_ml.requests[0]
    assert sent.body == b"\x00\x01data"
    assert sent.headers["Content-Type"] == "image/png"


def test_bearer_only_when_token(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/x", body={})
    request("GET", fake_ml.url + "/x")
    request("GET", fake_ml.url + "/x", token="test-token")
    assert "Authorization" not in fake_ml.requests[0].headers
    assert fake_ml.requests[1].headers["Authorization"] == "Bearer test-token"


def test_http_error_returns_status_and_json(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/x", status=404, body={"message": "nope"})
    assert request("GET", fake_ml.url + "/x") == (404, {"message": "nope"})


def test_non_json_error_body_is_truncated(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/x", status=502, body="<html>" + "a" * 2000 + "</html>")
    status, body = request("GET", fake_ml.url + "/x")
    assert status == 502
    assert isinstance(body, str)
    assert len(body) == 500


def test_empty_body_is_none(fake_ml: FakeML) -> None:
    fake_ml.route("DELETE", "/x", status=204)
    assert request("DELETE", fake_ml.url + "/x") == (204, None)


def test_network_error_raises_mlerror() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(MLError, match="Network error calling GET") as info:
        request("GET", f"http://127.0.0.1:{port}/x?secret=1")
    assert "secret" not in str(info.value)


def test_redirect_is_not_followed(fake_ml: FakeML, fake_other_host: FakeML) -> None:
    fake_other_host.route("GET", "/x", body={"leaked": True})
    fake_ml.route("GET", "/start", status=302, headers={"Location": f"{fake_other_host.url}/x"})
    status, _ = request("GET", fake_ml.url + "/start", token="test-token")
    assert status == 302
    assert fake_other_host.requests == []
    # The token went only to the first host.
    assert fake_ml.requests[0].headers["Authorization"] == "Bearer test-token"
    assert not any(
        "test-token" in r.headers.get("Authorization", "") for r in fake_other_host.requests
    )
