import json
import os
import stat
import urllib.parse
from pathlib import Path

import pytest
from fake_ml import FakeML

from mercadolivre_mcp.auth import (
    TokenStore,
    access_token,
    authorization_url,
    exchange_code,
    refresh,
)
from mercadolivre_mcp.config import Config
from mercadolivre_mcp.errors import AuthError, ConfigError

NEW_TOKEN = {
    "access_token": "new-access",
    "refresh_token": "new-refresh",
    "expires_in": 21600,
}


def test_save_sets_expires_at_with_margin(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "s", now=lambda: 1000.0)
    saved = store.save({"access_token": "a", "expires_in": 600})
    assert saved["expires_at"] == 1480
    assert store.load()["expires_at"] == 1480


def test_save_defaults_expires_in(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "s", now=lambda: 0.0)
    assert store.save({"access_token": "a"})["expires_at"] == 21600 - 120


def test_token_file_mode_0600(store: TokenStore) -> None:
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_secrets_dir_mode_0700(store: TokenStore) -> None:
    assert stat.S_IMODE(os.stat(store.path.parent).st_mode) == 0o700


def test_save_does_not_loosen_stricter_dir(tmp_path: Path) -> None:
    d = tmp_path / "s"
    d.mkdir()
    d.chmod(0o700)
    TokenStore(d).save({"access_token": "a"})
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_save_tightens_loose_dir(tmp_path: Path) -> None:
    d = tmp_path / "s"
    d.mkdir()
    d.chmod(0o755)
    TokenStore(d).save({"access_token": "a"})
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_save_tightens_existing_loose_file(tmp_path: Path) -> None:
    d = tmp_path / "s"
    d.mkdir()
    path = d / "token.json"
    path.write_text("{}")
    path.chmod(0o644)
    TokenStore(d).save({"access_token": "a"})
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_load_missing_raises_auth_error_with_hint(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="mercadolivre-mcp auth url"):
        TokenStore(tmp_path / "none").load()


def test_valid_token_does_not_refresh(config: Config, store: TokenStore, fake_ml: FakeML) -> None:
    assert access_token(config, store) == "test-access"
    assert fake_ml.requests == []


def test_expired_token_refreshes_and_saves(
    config: Config, store: TokenStore, fake_ml: FakeML
) -> None:
    store.save(
        {"access_token": "old", "refresh_token": "test-refresh", "user_id": 123, "expires_in": 0}
    )
    fake_ml.route("POST", "/oauth/token", body=NEW_TOKEN)
    assert access_token(config, store) == "new-access"
    form = fake_ml.requests[0].form
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "test-refresh"
    assert form["client_id"] == "test-client"
    assert form["client_secret"] == "test-secret"
    on_disk = json.loads(store.path.read_text())
    assert on_disk["access_token"] == "new-access"
    assert on_disk["user_id"] == 123


def test_force_refresh(config: Config, store: TokenStore, fake_ml: FakeML) -> None:
    fake_ml.route("POST", "/oauth/token", body=NEW_TOKEN)
    assert access_token(config, store, force_refresh=True) == "new-access"
    assert len(fake_ml.requests) == 1


def test_refresh_within_margin(config: Config, store: TokenStore, fake_ml: FakeML) -> None:
    store.save({"access_token": "old", "refresh_token": "test-refresh", "expires_in": 100})
    assert store.is_expired(store.load())
    fake_ml.route("POST", "/oauth/token", body=NEW_TOKEN)
    assert access_token(config, store) == "new-access"


def test_refresh_failure_raises_auth_error(
    config: Config, store: TokenStore, fake_ml: FakeML
) -> None:
    before = store.path.read_bytes()
    fake_ml.route("POST", "/oauth/token", status=400, body={"error": "invalid_grant"})
    with pytest.raises(AuthError) as info:
        refresh(config, store)
    message = str(info.value)
    assert "400" in message
    assert "invalid_grant" in message
    assert "auth url" in message
    assert "test-refresh" not in message
    assert store.path.read_bytes() == before


def test_refresh_without_credentials_raises_config_error(config: Config, store: TokenStore) -> None:
    bare = Config(secrets_dir=config.secrets_dir, api_base=config.api_base)
    with pytest.raises(ConfigError):
        refresh(bare, store)


def test_authorization_url_has_params(config: Config) -> None:
    url = authorization_url(config, "s1")
    parts = urllib.parse.urlsplit(url)
    assert parts.path == "/authorization"
    query = dict(urllib.parse.parse_qsl(parts.query))
    assert query["response_type"] == "code"
    assert query["state"] == "s1"
    assert query["client_id"] == "test-client"
    assert query["redirect_uri"] == "https://example.test/callback"


def test_exchange_code_saves_token(config: Config, fake_ml: FakeML) -> None:
    store = TokenStore(config.secrets_dir)
    fake_ml.route("POST", "/oauth/token", body={**NEW_TOKEN, "user_id": 7})
    saved = exchange_code(config, store, "TG-code")
    form = fake_ml.requests[0].form
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "TG-code"
    assert form["redirect_uri"] == "https://example.test/callback"
    assert saved["user_id"] == 7
    assert store.load()["access_token"] == "new-access"


def test_exchange_code_failure(config: Config, fake_ml: FakeML) -> None:
    store = TokenStore(config.secrets_dir)
    fake_ml.route("POST", "/oauth/token", status=400, body={"error": "invalid_grant"})
    with pytest.raises(AuthError, match=r"Authorization code exchange failed \(400\)"):
        exchange_code(config, store, "bad")
    assert not store.path.exists()
