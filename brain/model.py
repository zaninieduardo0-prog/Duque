from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, cast


@dataclass(slots=True)
class ModelResponse:
    text: str
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
    """Adapter da Responses API; a chave fica somente no ambiente."""

    def __init__(self, model: str | None = None, api_key: str | None = None, *, timeout: float = 60.0) -> None:
        self.model = model or os.getenv("DUQUE_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Pacote openai não instalado") from exc
        # Um cliente só (reaproveita conexões) e com limite de tempo: sem ele uma
        # chamada travada prende a requisição do HUD por vários minutos.
        self.client = OpenAI(api_key=self.api_key, timeout=timeout, max_retries=1)

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        kwargs.setdefault("store", False)
        response = self.client.responses.create(model=self.model, input=cast(Any, messages), **kwargs)
        text = getattr(response, "output_text", "") or ""
        return ModelResponse(text=text, raw=response)


def extract_json_object(text: str) -> dict[str, Any]:
    """Lê o primeiro objeto JSON da resposta, tolerando cercas ``` e texto ao redor."""
    cleaned = text.strip()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("A resposta do modelo não contém um objeto JSON")
    try:
        payload, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise ValueError("A resposta do modelo não é JSON válido") from exc
    if not isinstance(payload, dict):
        raise ValueError("A resposta do modelo deve ser um objeto JSON")
    return payload
