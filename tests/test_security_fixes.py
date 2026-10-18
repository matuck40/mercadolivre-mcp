"""Run the shared F1-F3 security scenarios against the new server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import security_scenarios
from fake_ml import FakeML

from mercadolivre_mcp.auth import TokenStore
from mercadolivre_mcp.client import MLClient
from mercadolivre_mcp.config import Config
from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS

SCENARIOS = sorted(name for name in dir(security_scenarios) if name.startswith("scenario_"))


class NewTarget:
    def __init__(self, config: Config, store: TokenStore, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._server = Server(TOOLS, lambda: MLClient(config, store))

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
        response = self._server.handle(message)
        assert response is not None and "result" in response, response
        return response["result"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_passes_on_new_code(
    scenario: str,
    config: Config,
    store: TokenStore,
    fake_ml: FakeML,
    fake_other_host: FakeML,
    tmp_path: Path,
) -> None:
    target = NewTarget(config, store, tmp_path)
    getattr(security_scenarios, scenario)(target, fake_ml, fake_other_host, tmp_path)
