"""OAuth token storage, refresh and authorization-code exchange."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import stat
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config
from .errors import AuthError
from .http import request

TOKEN_FILE = "token.json"  # noqa: S105 - a file name, not a secret
STATE_FILE = "oauth_state"
REFRESH_MARGIN_SECONDS = 120
DEFAULT_EXPIRES_IN = 21600


def _write_private(path: Path, payload: bytes) -> None:
    """Atomically write ``payload`` to ``path`` with mode 0600 (parent dir 0700).

    The bytes go to a new temp file in the same directory, which is fsynced and then
    renamed over ``path``. A failed or interrupted write leaves the old file untouched,
    which matters because a refresh token can be used only once.
    """
    directory = path.parent
    os.makedirs(directory, mode=0o700, exist_ok=True)
    dir_mode = stat.S_IMODE(os.stat(directory).st_mode)
    if dir_mode & 0o077:
        os.chmod(directory, dir_mode & 0o700)

    tmp = directory / f".{path.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)  # the umask cannot loosen it, but be explicit
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _fsync_dir(directory)


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself; not every platform can open a directory."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def save_oauth_state(secrets_dir: Path, state: str) -> None:
    """Persist the pending OAuth ``state`` (an empty string clears it)."""
    _write_private(Path(secrets_dir) / STATE_FILE, state.encode("utf-8"))


def load_oauth_state(secrets_dir: Path) -> str:
    """Return the saved OAuth ``state``, or an empty string when none is pending."""
    try:
        return (Path(secrets_dir) / STATE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class TokenStore:
    """Reads and writes the token file; only the owner can access it."""

    def __init__(self, secrets_dir: Path, now: Callable[[], float] = time.time):
        self.path = Path(secrets_dir) / TOKEN_FILE
        self._now = now

    def load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            raise AuthError(
                f"No token found in {self.path.parent}. "
                "Run `mercadolivre-mcp auth url` and then `mercadolivre-mcp auth code <code>`."
            ) from None
        except ValueError:
            raise AuthError(
                f"Token file {self.path} is not valid JSON. "
                "Run `mercadolivre-mcp auth url` to authorize again."
            ) from None
        if not isinstance(data, dict):
            raise AuthError(
                f"Token file {self.path} is malformed. "
                "Run `mercadolivre-mcp auth url` to authorize again."
            )
        return data

    def save(self, token: dict[str, Any]) -> dict[str, Any]:
        saved = dict(token)
        expires_in = saved.get("expires_in")
        if expires_in is None:
            expires_in = DEFAULT_EXPIRES_IN
        saved["expires_at"] = self._now() + float(expires_in) - REFRESH_MARGIN_SECONDS

        _write_private(self.path, json.dumps(saved, indent=2).encode("utf-8"))
        return saved

    def is_expired(self, token: dict[str, Any]) -> bool:
        return self._now() >= token.get("expires_at", 0)


def _post_token(config: Config, form: dict[str, str]) -> tuple[int, Any]:
    return request("POST", f"{config.api_base}/oauth/token", form=form)


def _body_text(body: Any) -> str:
    return body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)


def refresh(config: Config, store: TokenStore) -> dict[str, Any]:
    config.require("client_id", "client_secret")
    old = store.load()
    status, body = _post_token(
        config,
        {
            "grant_type": "refresh_token",
            "client_id": str(config.client_id),
            "client_secret": str(config.client_secret),
            "refresh_token": str(old.get("refresh_token", "")),
        },
    )
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        raise AuthError(
            f"Token refresh failed ({status}): {_body_text(body)}. "
            "Run `mercadolivre-mcp auth url` to authorize again."
        )
    new = dict(body)
    if "user_id" not in new and "user_id" in old:
        new["user_id"] = old["user_id"]
    if "refresh_token" not in new and "refresh_token" in old:
        new["refresh_token"] = old["refresh_token"]
    return store.save(new)


def access_token(config: Config, store: TokenStore, force_refresh: bool = False) -> str:
    token = store.load()
    if force_refresh or store.is_expired(token):
        token = refresh(config, store)
    return str(token["access_token"])


def authorization_url(config: Config, state: str) -> str:
    config.require("client_id", "redirect_uri")
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": str(config.client_id),
            "redirect_uri": str(config.redirect_uri),
            "state": state,
        }
    )
    return f"{config.auth_base}/authorization?{query}"


def exchange_code(config: Config, store: TokenStore, code: str) -> dict[str, Any]:
    config.require("client_id", "client_secret", "redirect_uri")
    status, body = _post_token(
        config,
        {
            "grant_type": "authorization_code",
            "client_id": str(config.client_id),
            "client_secret": str(config.client_secret),
            "code": code,
            "redirect_uri": str(config.redirect_uri),
        },
    )
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        raise AuthError(f"Authorization code exchange failed ({status}): {_body_text(body)}")
    return store.save(body)
