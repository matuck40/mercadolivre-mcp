"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_ml import FakeML

from mercadolivre_mcp.auth import TokenStore
from mercadolivre_mcp.config import Config


@pytest.fixture
def fake_ml() -> Iterator[FakeML]:
    """Fake Mercado Livre API at http://127.0.0.1:<port>."""
    server = FakeML()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def fake_other_host() -> Iterator[FakeML]:
    """Second, independent fake whose host (localhost) differs from fake_ml's."""
    server = FakeML(advertised_host="localhost")
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def config(tmp_path: Path, fake_ml: FakeML) -> Config:
    return Config(
        secrets_dir=tmp_path / "secrets",
        client_id="test-client",
        client_secret="test-secret",
        redirect_uri="https://example.test/callback",
        api_base=fake_ml.url,
        auth_base=fake_ml.url,
    )


@pytest.fixture
def store(config: Config) -> TokenStore:
    token_store = TokenStore(config.secrets_dir)
    token_store.save(
        {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "user_id": 123,
            "expires_in": 21600,
        }
    )
    return token_store
