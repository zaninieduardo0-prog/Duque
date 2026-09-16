from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelResponse:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None


class ModelAdapter(ABC):
    """Contrato único para qualquer modelo que dê inteligência ao Duque."""

    @abstractmethod
    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        raise NotImplementedError


class NullModel(ModelAdapter):
    """Adapter offline para testes da arquitetura sem API ou internet."""

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        last = messages[-1]["content"] if messages else ""
        return ModelResponse(text=last)
