from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    required: tuple[str, ...] = ()
    argument_types: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ValidationResult:
    valid: bool
    error: str | None = None


class ToolSchemaRegistry:
    """Catálogo simples para validar planos e ações antes de executá-los."""

    def __init__(self) -> None:
        self._schemas: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._schemas[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._schemas.get(name)

    def names(self) -> list[str]:
        return sorted(self._schemas)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "required": list(spec.required),
                "arguments": {key: self._type_label(value) for key, value in spec.argument_types.items()},
            }
            for spec in self._schemas.values()
        ]

    def validate(self, name: str, arguments: dict[str, Any] | None) -> ValidationResult:
        spec = self.get(name)
        if spec is None:
            return ValidationResult(False, f"Ferramenta sem schema: {name}")
        args = arguments or {}
        missing = [key for key in spec.required if key not in args]
        if missing:
            return ValidationResult(False, f"Argumentos obrigatórios ausentes: {', '.join(missing)}")
        allowed = set(spec.argument_types) | set(spec.required)
        unexpected = [key for key in args if key not in allowed]
        if unexpected:
            return ValidationResult(False, f"Argumentos não suportados: {', '.join(unexpected)}")
        for key, expected in spec.argument_types.items():
            if key not in args:
                continue
            value = args[key]
            expected_types = expected if isinstance(expected, tuple) else (expected,)
            numeric = int in expected_types or float in expected_types
            if numeric and bool not in expected_types and isinstance(value, bool):
                # bool é subclasse de int, mas "pid=True" ou "delay_seconds=False" não são números.
                return ValidationResult(False, f"Argumento '{key}' deve ser {self._type_label(expected)}")
            if int in expected_types and float not in expected_types and isinstance(value, float) and value.is_integer():
                # Modelos costumam mandar 3.0 em vez de 3.
                args[key] = int(value)
                continue
            if not isinstance(value, expected):
                return ValidationResult(False, f"Argumento '{key}' deve ser {self._type_label(expected)}")
        return ValidationResult(True)

    @staticmethod
    def _type_label(expected: Any) -> str:
        if isinstance(expected, tuple):
            return " ou ".join(item.__name__ for item in expected)
        return getattr(expected, "__name__", str(expected))
