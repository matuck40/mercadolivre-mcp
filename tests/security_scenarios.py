"""Target-agnostic security scenarios for the three fixes F1-F3.

Each scenario drives a ``Target`` (anything that can run an MCP tool call) against
fake servers and checks the observable behavior with plain asserts. The same
functions are run against the new server and against the original implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from fake_ml import FakeML, RecordedRequest

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PRIVATE_KEY = (
    b"-----BEGIN OPENSSH PRIVATE KEY-----\n"
    b"b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    b"-----END OPENSSH PRIVATE KEY-----\n"
)


class Target(Protocol):
    """Something that executes an MCP tool call and returns the ``result`` object."""

    base_dir: Path  # where a relative file path would be resolved

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


def _upload_route(fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/pictures/items/upload", body={"id": "000000-MLB000000001_000000"})


def scenario_upload_refuses_non_image(
    target: Target, fake_ml: FakeML, fake_other_host: FakeML, tmp_path: Path
) -> None:
    _upload_route(fake_ml)
    key = tmp_path / "key.png"
    key.write_bytes(PRIVATE_KEY)
    result = target.call_tool("ml_upload_picture", {"file_path": str(key)})
    assert result.get("isError"), f"non-image was accepted: {result}"
    assert fake_ml.writes() == [], (
        f"file content was uploaded: {[r.body[:80] for r in fake_ml.writes()]}"
    )


def scenario_upload_refuses_relative_path(
    target: Target, fake_ml: FakeML, fake_other_host: FakeML, tmp_path: Path
) -> None:
    _upload_route(fake_ml)
    photo = target.base_dir / "photo.png"
    photo.write_bytes(PNG_BYTES)
    assert photo.is_file()  # the file exists where a relative path would resolve
    result = target.call_tool("ml_upload_picture", {"file_path": "photo.png"})
    assert result.get("isError"), f"relative path was accepted: {result}"
    assert fake_ml.writes() == [], (
        f"file content was uploaded: {[r.body[:80] for r in fake_ml.writes()]}"
    )


def scenario_redirect_does_not_leak_token(
    target: Target, fake_ml: FakeML, fake_other_host: FakeML, tmp_path: Path
) -> None:
    fake_ml.route(
        "GET",
        "/users/me",
        status=302,
        body={},
        headers={"Location": f"{fake_other_host.url}/users/me"},
    )
    fake_other_host.route("GET", "/users/me", body={"id": 123, "nickname": "TESTUSER"})
    target.call_tool("ml_get_account", {})
    assert "/users/me" in [r.path for r in fake_ml.requests], "no request reached the API"
    leaked: list[RecordedRequest] = [
        r for r in fake_other_host.requests if "Authorization" in r.headers
    ]
    assert leaked == [], (
        f"token sent to another host: {[r.headers['Authorization'] for r in leaked]}"
    )


def scenario_ambiguous_path_sends_nothing(
    target: Target, fake_ml: FakeML, fake_other_host: FakeML, tmp_path: Path
) -> None:
    result = target.call_tool("ml_api_get", {"path": "//evil.test/x"})
    assert result.get("isError"), f"ambiguous path was accepted: {result}"
    assert fake_ml.requests == [], f"requests were sent: {[r.path for r in fake_ml.requests]}"


def scenario_401_refreshes_and_retries(
    target: Target, fake_ml: FakeML, fake_other_host: FakeML, tmp_path: Path
) -> None:
    calls: list[int] = []

    def users_me(request: RecordedRequest) -> tuple[int, Any]:
        calls.append(1)
        if len(calls) == 1:
            return 401, {"message": "invalid_token"}
        return 200, {"id": 123, "nickname": "TESTUSER"}

    fake_ml.route("GET", "/users/me", handler=users_me)
    fake_ml.route(
        "POST",
        "/oauth/token",
        body={
            "access_token": "test-access-2",
            "refresh_token": "test-refresh-2",
            "expires_in": 21600,
            "user_id": 123,
        },
    )
    result = target.call_tool("ml_get_account", {})
    assert not result.get("isError"), f"401 was not recovered: {result}"
    refreshes = [r for r in fake_ml.requests if r.path == "/oauth/token"]
    assert len(refreshes) == 1, f"expected one refresh, saw {len(refreshes)}"
    last = [r for r in fake_ml.requests if r.path == "/users/me"][-1]
    assert last.headers.get("Authorization") == "Bearer test-access-2"
