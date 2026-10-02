from __future__ import annotations

import os
from typing import Any

from ..model import ModelAdapter, ModelResponse

DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"


def to_anthropic_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """Converte o histórico do Duque para o formato da API da Anthropic.

    - mensagens "system" viram o parâmetro `system`;
    - papéis consecutivos iguais são unidos (a API exige alternância);
    - a conversa sempre começa pelo usuário.
    """
    system_parts: list[str] = []
    converted: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "user")
        content = str(message.get("content", ""))
        if role == "system":
            system_parts.append(content)
            continue
        role = "assistant" if role == "assistant" else "user"
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"] += "\n\n" + content
        else:
            converted.append({"role": role, "content": content})
    if not converted or converted[0]["role"] != "user":
        converted.insert(0, {"role": "user", "content": "(início)"})
    return "\n\n".join(system_parts), converted


class ClaudeAdapter(ModelAdapter):
    """Adapter isolado para os modelos Claude (API da Anthropic).

    A chave fica somente no ambiente (ANTHROPIC_API_KEY); nada do restante do
    Duque conhece o SDK.
    """

    def __init__(self, model: str | None = None, *, max_tokens: int = 8000, client: Any | None = None) -> None:
        self.model = model or os.getenv("DUQUE_DEV_MODEL") or DEFAULT_CLAUDE_MODEL
        self.max_tokens = max_tokens
        if client is not None:
            self.client = client
            return
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY não configurada")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("Pacote 'anthropic' não instalado (pip install anthropic)") from exc
        self.client = anthropic.Anthropic()

    def respond(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        system, converted = to_anthropic_messages(messages)
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
            "messages": converted,
            **kwargs,
        }
        if system:
            params["system"] = system
        response = self.client.messages.create(**params)
        text = "".join(
            getattr(block, "text", "") for block in getattr(response, "content", []) if getattr(block, "type", "text") == "text"
        )
        return ModelResponse(text=text, raw=response)
