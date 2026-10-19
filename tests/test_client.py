"""Tests for the authenticated client."""

from __future__ import annotations

import pytest
from fake_ml import FakeML

from mercadolivre_mcp.auth import TokenStore
from mercadolivre_mcp.client import MLClient
from mercadolivre_mcp.config import Config
from mercadolivre_mcp.errors import APIError, AuthError, ToolInputError


def _token_route(fake_ml: FakeML) -> None:
    fake_ml.route(
        "POST",
        "/oauth/token",
        body={
            "access_token": "test-access-2",
            "refresh_token": "test-refresh-2",
            "expires_in": 21600,
        },
    )


def _flaky(fake_ml: FakeML, method: str, path: str) -> None:
    calls = {"n": 0}

    def handler(_req):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return (401, {"message": "invalid token"}) if calls["n"] == 1 else (200, {"ok": True})

    fake_ml.route(method, path, handler=handler)


def test_get_sends_bearer(client: MLClient, fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/items/MLB000000001", body={"id": "MLB000000001"})
    assert client.get("/items/MLB000000001") == {"id": "MLB000000001"}
    assert fake_ml.requests[0].headers["Authorization"] == "Bearer test-access"


def test_api_error_message(client: MLClient, fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/items/X", status=404, body={"message": "not found"})
    with pytest.raises(APIError) as exc:
        client.get("/items/X?attributes=id")
    assert str(exc.value).startswith("GET /items/X -> 404: ")
    assert exc.value.status == 404


def test_redirect_is_api_error(client: MLClient, fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/r", status=302, headers={"Location": "http://evil.test/"})
    with pytest.raises(APIError) as exc:
        client.get("/r")
    assert exc.value.status == 302


def test_401_triggers_single_refresh_and_retry(client: MLClient, fake_ml: FakeML) -> None:
    _token_route(fake_ml)
    _flaky(fake_ml, "GET", "/users/me")
    assert client.get("/users/me") == {"ok": True}
    assert [r.path for r in fake_ml.requests].count("/oauth/token") == 1
    gets = [r for r in fake_ml.requests if r.path == "/users/me"]
    assert len(gets) == 2
    assert gets[0].headers["Authorization"] == "Bearer test-access"
    assert gets[1].headers["Authorization"] == "Bearer test-access-2"


def test_401_retry_applies_to_put_with_identical_body(client: MLClient, fake_ml: FakeML) -> None:
    _token_route(fake_ml)
    _flaky(fake_ml, "PUT", "/items/MLB000000001")
    assert client.put("/items/MLB000000001", {"price": 10}) == {"ok": True}
    puts = [r for r in fake_ml.requests if r.method == "PUT"]
    assert len(puts) == 2
    assert puts[0].body == puts[1].body
    assert puts[1].headers["Authorization"] == "Bearer test-access-2"


def test_401_after_refresh_raises_auth_error(client: MLClient, fake_ml: FakeML) -> None:
    _token_route(fake_ml)
    fake_ml.route("GET", "/users/me", status=401, body={"message": "invalid token"})
    with pytest.raises(AuthError, match="mercadolivre-mcp auth url"):
        client.get("/users/me")
    paths = [r.path for r in fake_ml.requests]
    assert paths.count("/oauth/token") == 1
    assert paths.count("/users/me") == 2


def test_user_id_from_token_file(client: MLClient, fake_ml: FakeML) -> None:
    assert client.user_id() == 123
    assert fake_ml.requests == []


def test_user_id_falls_back_to_users_me(config: Config, store: TokenStore, fake_ml: FakeML) -> None:
    store.save(
        {"access_token": "test-access", "refresh_token": "test-refresh", "expires_in": 21600}
    )
    fake_ml.route("GET", "/users/me", body={"id": 456})
    assert MLClient(config, store).user_id() == 456


def test_upload_multipart(client: MLClient, fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/pictures/items/upload", body={"id": "pic1"})
    data = b"\x89PNG\r\n\x1a\nbytes"
    assert client.upload("/pictures/items/upload", data, "a.png", "image/png") == {"id": "pic1"}
    req = fake_ml.requests[0]
    assert req.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="a.png"' in req.body
    assert data in req.body


@pytest.mark.parametrize(
    "path",
    ["items", "//evil.test/x", "/x?u=http://evil.test", "/items/1\r\nX: y", "/items 1"],
)
def test_url_guard(client: MLClient, fake_ml: FakeML, path: str) -> None:
    with pytest.raises(ToolInputError, match="relative API path"):
        client.get(path)
    assert fake_ml.requests == []
