from pathlib import Path

import pytest

from mercadolivre_mcp.config import Config
from mercadolivre_mcp.errors import APIError, ConfigError, MLError


def test_default_secrets_dir():
    assert Config.from_env({}).secrets_dir == Path.home() / ".config" / "mercadolivre-mcp"


def test_env_overrides(tmp_path):
    config = Config.from_env(
        {
            "ML_SECRETS_DIR": str(tmp_path),
            "ML_CLIENT_ID": "id-1",
            "ML_CLIENT_SECRET": "test-secret",
            "ML_REDIRECT_URI": "https://example.test/callback",
        }
    )
    assert config.secrets_dir == tmp_path
    assert config.client_id == "id-1"
    assert config.client_secret == "test-secret"
    assert config.redirect_uri == "https://example.test/callback"
    assert config.api_base == "https://api.mercadolibre.com"
    assert config.auth_base == "https://auth.mercadolivre.com.br"


def test_tilde_expanded():
    config = Config.from_env({"ML_SECRETS_DIR": "~/somewhere"})
    assert config.secrets_dir == Path.home() / "somewhere"


def test_empty_string_is_unset():
    config = Config.from_env({"ML_SECRETS_DIR": "", "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": ""})
    assert config.secrets_dir == Path.home() / ".config" / "mercadolivre-mcp"
    assert config.client_id is None
    assert config.client_secret is None


def test_require_lists_missing_vars():
    config = Config.from_env({"ML_REDIRECT_URI": "https://example.test/cb"})
    with pytest.raises(ConfigError) as info:
        config.require("client_id", "client_secret", "redirect_uri")
    assert str(info.value) == "Missing environment variable(s): ML_CLIENT_ID, ML_CLIENT_SECRET"


def test_require_passes_when_set_and_rejects_unknown_names():
    config = Config.from_env({"ML_CLIENT_ID": "x"})
    config.require("client_id")
    with pytest.raises(ValueError):
        config.require("nope")


def test_from_env_reads_no_file(tmp_path):
    (tmp_path / "mercadolivre.env").write_text("ML_CLIENT_ID=x\n")
    config = Config.from_env({"ML_SECRETS_DIR": str(tmp_path)})
    assert config.client_id is None


def test_api_error_message_and_attrs():
    err = APIError("GET", "/users/me", 404, {"message": "nope"})
    assert isinstance(err, MLError)
    assert err.status == 404
    assert err.body == {"message": "nope"}
    assert str(err) == 'GET /users/me -> 404: {"message": "nope"}'
    assert str(APIError("GET", "/x", 500, "boom")) == "GET /x -> 500: boom"
