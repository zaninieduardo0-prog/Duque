from __future__ import annotations

import os
from typing import Any, cast

from ..model import ModelAdapter, ModelResponse


class OpenAIAdapter(ModelAdapter):
    """Adapter isolado para o provedor OpenAI.

    A dependência fica aqui para que o restante do Duque não precise conhecer
    detalhes do SDK ou da configuração da API.
    """

    def __init__(self, model: str = "gpt-5.6") -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Pacote 'openai' não instalado") from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")

        self.model = model
        self.client = OpenAI(api_key=api_key)

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        response = self.client.responses.create(
            model=self.model,
            input=cast(Any, messages),
            **kwargs,
        )
        return ModelResponse(
            text=getattr(response, "output_text", "") or "",
            raw=response,
        )
