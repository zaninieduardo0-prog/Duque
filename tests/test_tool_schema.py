from __future__ import annotations

from brain.tool_schema import ToolSchemaRegistry, ToolSpec


def make_registry() -> ToolSchemaRegistry:
    registry = ToolSchemaRegistry()
    registry.register(ToolSpec("echo", "Retorna valor", ("value",), {"value": str}))
    return registry


def test_schema_rejects_missing_required_argument() -> None:
    result = make_registry().validate("echo", {})
    assert not result.valid
    assert "obrigatórios" in (result.error or "")


def test_schema_rejects_unexpected_argument() -> None:
    result = make_registry().validate("echo", {"value": "ok", "extra": True})
    assert not result.valid
    assert "não suportados" in (result.error or "")


def test_schema_accepts_valid_arguments() -> None:
    result = make_registry().validate("echo", {"value": "ok"})
    assert result.valid


def test_schema_rejects_unknown_tool() -> None:
    result = make_registry().validate("missing", {})
    assert not result.valid
    assert "sem schema" in (result.error or "")
