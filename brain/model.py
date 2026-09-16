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


class OpenAIResponsesModel(ModelAdapter):
    """Adapter opcional para a Responses API; a chave fica somente no ambiente."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        import os
        self.model = model or os.getenv("DUQUE_MODEL", "gpt-5")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Pacote openai não instalado") from exc

        client = OpenAI(api_key=self.api_key)
        response = client.responses.create(model=self.model, input=messages, **kwargs)
        text = getattr(response, "output_text", "") or ""
        return ModelResponse(text=text, raw=response)
