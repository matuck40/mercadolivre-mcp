"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fake_ml import FakeML


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
