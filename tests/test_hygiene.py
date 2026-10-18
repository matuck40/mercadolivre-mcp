"""Repository hygiene: tool registry, annotations, no personal strings, ASCII descriptions."""

from pathlib import Path

from mercadolivre_mcp.tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent

EXPECTED_TOOLS = {
    "ml_get_account",
    "ml_list_items",
    "ml_get_item",
    "ml_get_item_visits",
    "ml_list_questions",
    "ml_list_orders",
    "ml_api_get",
    "ml_update_item",
    "ml_upload_picture",
    "ml_answer_question",
}
GATED = ("ml_update_item", "ml_answer_question")


def test_registry_has_the_ten_tools():
    assert set(TOOLS) == EXPECTED_TOOLS
    assert len(TOOLS) == 10


def test_every_tool_has_a_test():
    excluded = {"test_hygiene.py", "test_conformance.py"}
    sources = [
        path.read_text(encoding="utf-8")
        for path in sorted(TESTS.glob("test_*.py"))
        if path.name not in excluded
    ]
    for name in TOOLS:
        assert any(name in text for text in sources), f"no test mentions {name}"


def test_write_tools_annotations():
    assert TOOLS["ml_update_item"].annotations["destructiveHint"] is True
    assert TOOLS["ml_answer_question"].annotations["readOnlyHint"] is False
    assert TOOLS["ml_upload_picture"].annotations["readOnlyHint"] is False
    for name, tool in TOOLS.items():
        if name not in ("ml_update_item", "ml_answer_question", "ml_upload_picture"):
            assert tool.annotations["readOnlyHint"] is True, name


def test_gated_tools_have_confirm_default_false():
    for name in GATED:
        props = TOOLS[name].input_schema["properties"]
        assert props["confirm"]["type"] == "boolean", name
        assert props["confirm"]["default"] is False, name
        assert "confirm" not in TOOLS[name].input_schema.get("required", []), name


def test_no_personal_strings_in_source():
    # (needle, case-insensitive). The home-directory needle stays case-sensitive because
    # API paths such as "/users/me" are legitimate.
    needles = [
        ("/Us" + "ers/", False),
        ("lucca" + "matuck", True),
        ("Em Ca" + "madas", True),
        ("segre" + "dos", False),
    ]
    files = [ROOT / "README.md", ROOT / "pyproject.toml"]
    for folder in (ROOT / "src", TESTS):
        for path in folder.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.parent == TESTS / "fixtures" and path.suffix == ".json":
                continue
            files.append(path)
    hits = []
    for path in files:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle, ignore_case in needles:
            found = needle.lower() in text.lower() if ignore_case else needle in text
            if found:
                hits.append(f"{path.relative_to(ROOT)}: {needle!r}")
    assert not hits, hits


def test_descriptions_are_ascii_english():
    for name, tool in TOOLS.items():
        assert tool.title.isascii(), name
        assert tool.description.isascii(), name
        for prop, spec in tool.input_schema.get("properties", {}).items():
            assert spec.get("description", "").isascii(), f"{name}.{prop}"
