from __future__ import annotations

from .model import ModelAdapter, ModelResponse


class BrainAgent:
    """Camada de raciocínio que conhece apenas o contrato ModelAdapter."""

    def __init__(self, model: ModelAdapter) -> None:
        self.model = model

    def respond(self, user_text: str, *, system: str | None = None) -> ModelResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_text})
        return self.model.respond(messages)
