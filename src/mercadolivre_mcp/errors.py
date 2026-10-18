"""Exception types shared across the package."""

import json
from typing import Any


class MLError(Exception):
    """Base class for all errors raised by this package."""


class ConfigError(MLError):
    """Required configuration is missing or invalid."""


class AuthError(MLError):
    """Authentication with Mercado Livre failed or is not set up."""


class ToolInputError(MLError):
    """A tool was called with invalid arguments."""


class APIError(MLError):
    """The Mercado Livre API answered with an error status."""

    def __init__(self, method: str, path: str, status: int, body: Any):
        self.method = method
        self.path = path
        self.status = status
        self.body = body
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        super().__init__(f"{method} {path} -> {status}: {text}")
