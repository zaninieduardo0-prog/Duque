from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    required: tuple[str, ...] = ()
    argument_types: dict[str, type] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ValidationResult:
    valid: bool
    error: str | None = None


class ToolSchemaRegistry:
    """Catálogo simples para validar planos antes de executá-los."""

    def __init__(self) -> None:
        self._schemas: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._schemas[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._schemas.get(name)

    def validate(self, name: str, arguments: dict[str, Any] | None) -> ValidationResult:
        spec = self.get(name)
        if spec is None:
            return ValidationResult(False, f"Ferramenta sem schema: {name}")
        args = arguments or {}
        missing = [key for key in spec.required if key not in args]
        if missing:
            return ValidationResult(False, f"Argumentos obrigatórios ausentes: {', '.join(missing)}")
        for key, expected in spec.argument_types.items():
            if key in args and not isinstance(args[key], expected):
                return ValidationResult(False, f"Argumento '{key}' deve ser {expected.__name__}")
        return ValidationResult(True)
