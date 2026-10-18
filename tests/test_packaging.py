import tomllib
from pathlib import Path

from mercadolivre_mcp import cli

ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_no_runtime_dependencies():
    assert _pyproject()["project"]["dependencies"] == []


def test_dev_dependencies_are_pinned():
    dev = _pyproject()["dependency-groups"]["dev"]
    assert dev and all("==" in d for d in dev)


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "mercadolivre-mcp 0.1.0"
