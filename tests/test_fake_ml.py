from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

from fake_ml import FakeML, RecordedRequest


def _call(url: str, method: str = "GET", data: bytes | None = None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})  # noqa: S310
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_routes_json_and_records_request(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/users/me", body={"id": 1})
    status, body = _call(
        fake_ml.url + "/users/me?a=1", headers={"Authorization": "Bearer test-token"}
    )
    assert status == 200
    assert json.loads(body) == {"id": 1}
    assert fake_ml.requests[0].query == {"a": ["1"]}
    assert fake_ml.requests[0].path == "/users/me"
    assert fake_ml.requests[0].headers["Authorization"] == "Bearer test-token"


def test_unrouted_returns_404(fake_ml: FakeML) -> None:
    status, body = _call(fake_ml.url + "/nope")
    assert status == 404
    assert json.loads(body) == {"message": "not found"}


def test_handler_receives_body(fake_ml: FakeML) -> None:
    seen: list[RecordedRequest] = []

    def handler(req: RecordedRequest):
        seen.append(req)
        return 201, {"ok": True}

    fake_ml.route("POST", "/items", handler=handler)
    status, body = _call(
        fake_ml.url + "/items",
        method="POST",
        data=json.dumps({"title": "x"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert status == 201
    assert json.loads(body) == {"ok": True}
    assert seen[0].json == {"title": "x"}


def test_form_and_raw_body(fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/oauth/token", body="raw-text")
    status, body = _call(
        fake_ml.url + "/oauth/token",
        method="POST",
        data=b"grant_type=refresh_token&refresh_token=r1",
    )
    assert (status, body) == (200, b"raw-text")
    assert fake_ml.requests[0].form == {"grant_type": "refresh_token", "refresh_token": "r1"}
    assert fake_ml.requests[0].json is None


def test_writes_filters_get(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/a")
    fake_ml.route("PUT", "/a")
    _call(fake_ml.url + "/a")
    _call(fake_ml.url + "/a", method="PUT", data=b"{}")
    assert [r.method for r in fake_ml.requests] == ["GET", "PUT"]
    assert [r.method for r in fake_ml.writes()] == ["PUT"]


def test_other_host_is_independent_and_differs(fake_ml: FakeML, fake_other_host: FakeML) -> None:
    assert fake_ml.url.startswith("http://127.0.0.1:")
    assert fake_other_host.url.startswith("http://localhost:")
    fake_other_host.route("GET", "/x", body={"from": "other"})
    status, body = _call(fake_other_host.url + "/x")
    assert (status, json.loads(body)) == (200, {"from": "other"})
    assert fake_ml.requests == []


def test_route_headers_and_redirect_not_followed(fake_ml: FakeML, fake_other_host: FakeML) -> None:
    target = fake_other_host.url + "/x"
    fake_ml.route("GET", "/r", status=302, headers={"Location": target})
    fake_ml.route(
        "GET", "/h", handler=lambda req: (307, {"a": 1}, {"Location": target, "X-Test": "1"})
    )
    host, port = fake_ml.url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port))
    conn.request("GET", "/r")
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 302
    assert resp.getheader("Location") == target
    conn.request("GET", "/h")
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 307
    assert resp.getheader("Location") == target
    assert resp.getheader("X-Test") == "1"
    conn.close()


def test_handler_exception_returns_500(fake_ml: FakeML) -> None:
    def boom(req: RecordedRequest):
        raise ValueError("bad thing")

    fake_ml.route("GET", "/boom", handler=boom)
    status, body = _call(fake_ml.url + "/boom")
    assert status == 500
    assert json.loads(body) == {"message": "ValueError: bad thing"}


def test_request_headers_are_case_insensitive(fake_ml: FakeML) -> None:
    fake_ml.route("GET", "/a")
    _call(fake_ml.url + "/a", headers={"Authorization": "Bearer test-token"})
    headers = fake_ml.requests[0].headers
    assert headers["authorization"] == "Bearer test-token"
    assert headers["Authorization"] == "Bearer test-token"
    assert headers.get("AUTHORIZATION") == "Bearer test-token"
    assert "authorization" in headers
