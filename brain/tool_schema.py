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
        # Ferramenta segura e delimitada à Área de Trabalho. O registro aqui
        # garante que o Planner possa usá-la mesmo antes do catálogo operacional
        # do AgentLoop ser preenchido.
        self.register(ToolSpec(
            "write_desktop_file",
            "Cria um arquivo somente na Área de Trabalho",
            ("filename", "content"),
            {"filename": str, "content": str},
        ))

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
            if key in args and not isinstance(args[key], expected):
                label = self._type_label(expected)
                return ValidationResult(False, f"Argumento '{key}' deve ser {label}")
        return ValidationResult(True)

    @staticmethod
    def _type_label(expected: Any) -> str:
        if isinstance(expected, tuple):
            return " ou ".join(item.__name__ for item in expected)
        return getattr(expected, "__name__", str(expected))
