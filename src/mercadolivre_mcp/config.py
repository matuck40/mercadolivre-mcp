"""Configuration, read from environment variables only (no config file)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

DEFAULT_SECRETS_DIR = "~/.config/mercadolivre-mcp"

# Config field name -> environment variable name.
_ENV_VARS = {
    "client_id": "ML_CLIENT_ID",
    "client_secret": "ML_CLIENT_SECRET",
    "redirect_uri": "ML_REDIRECT_URI",
}


@dataclass(frozen=True)
class Config:
    secrets_dir: Path
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None
    api_base: str = "https://api.mercadolibre.com"
    auth_base: str = "https://auth.mercadolivre.com.br"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ

        def get(name: str) -> str | None:
            return env.get(name) or None

        secrets_dir = Path(get("ML_SECRETS_DIR") or DEFAULT_SECRETS_DIR).expanduser()
        return cls(
            secrets_dir=secrets_dir,
            client_id=get("ML_CLIENT_ID"),
            client_secret=get("ML_CLIENT_SECRET"),
            redirect_uri=get("ML_REDIRECT_URI"),
        )

    def require(self, *names: str) -> None:
        """Raise ConfigError listing the env vars of the unset fields, in the order given."""
        unknown = [name for name in names if name not in _ENV_VARS]
        if unknown:
            raise ValueError(f"Unknown config field(s): {', '.join(unknown)}")
        missing = [_ENV_VARS[name] for name in names if not getattr(self, name)]
        if missing:
            raise ConfigError(f"Missing environment variable(s): {', '.join(missing)}")
