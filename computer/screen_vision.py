"""'Duque, o que tem na minha tela?': captura a tela e pede a um modelo de
visão uma explicação curta, em português, pronta para ser falada.

A imagem vai para o provedor de visão (OpenAI por padrão) só quando o Du pede.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

PROMPT = (
    "Você é o Duque, assistente pessoal do Du, olhando a tela do computador dele. "
    "{question}\n"
    "Responda em português do Brasil, em no máximo 4 frases curtas, naturais para serem faladas. "
    "Se houver um erro, diga qual é e a provável solução. Não descreva elementos irrelevantes da interface."
)
DEFAULT_QUESTION = "Diga o que está na tela e o que parece importante."


def _default_capture() -> Any:
    if not sys.platform.startswith("win"):
        raise RuntimeError("captura de tela disponível apenas no Windows")
    from PIL import ImageGrab

    return ImageGrab.grab()


def _downscale(image: Any, limit: int = 1600) -> Any:
    try:
        copy = image.copy()
        copy.thumbnail((limit, limit))
        return copy
    except Exception:
        return image


class ScreenVision:
    def __init__(self, capture: Callable[[], Any] | None = None, adapter: Any | None = None) -> None:
        self.capture = capture or _default_capture
        self.adapter = adapter

    def _adapter(self) -> Any:
        if self.adapter is None:
            from brain.vision import OpenAIResponsesVisionAdapter

            self.adapter = OpenAIResponsesVisionAdapter(model=os.getenv("DUQUE_VISION_MODEL") or "gpt-4o-mini")
        return self.adapter

    def describe_screen(self, question: str = "") -> dict[str, Any]:
        try:
            image = _downscale(self.capture())
        except Exception as exc:
            return {"success": False, "error": f"Não consegui capturar a tela: {exc}"}
        try:
            response = self._adapter().analyze(image, PROMPT.format(question=question.strip() or DEFAULT_QUESTION))
        except Exception as exc:
            return {"success": False, "error": f"A análise da tela falhou: {type(exc).__name__}: {exc}"}
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return {"success": False, "error": "O modelo de visão não respondeu."}
        return {"message": text}
