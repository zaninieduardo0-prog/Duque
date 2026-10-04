from __future__ import annotations

import json
from typing import Any

from brain.vision import NullVisionAdapter, VisionAdapter

from .perception import ScreenCapture, ScreenAnalyzer


VISION_PROMPT = """
Analise esta captura de tela para um agente de computador.
Retorne SOMENTE JSON válido, sem markdown, neste formato:
{
  "summary": "resumo curto",
  "foreground_target": "janela ou app principal, se identificável",
  "ocr_text": "texto legível relevante",
  "elements": [
    {
      "type": "button|field|link|text|window|icon|other",
      "text": "texto visível, se houver",
      "x": 0,
      "y": 0,
      "width": 0,
      "height": 0,
      "confidence": 0.0
    }
  ]
}
Inclua apenas elementos que consiga localizar visualmente. Não invente coordenadas.
As coordenadas devem ser absolutas em pixels desta imagem, com origem no canto
superior esquerdo.
""".strip()

# Imagens menores custam menos tokens e latência; as coordenadas voltam para o
# espaço da captura original antes de serem usadas em cliques.
MAX_SENT_WIDTH = 1280


class ModelVisionAnalyzer(ScreenAnalyzer):
    """Adiciona visão multimodal opcional à percepção local do Windows.

    A decisão de ativar (DUQUE_ENABLE_MODEL_VISION) fica no runtime.
    """

    def __init__(self, adapter: VisionAdapter | None = None, *, unavailable_reason: str | None = None) -> None:
        self.adapter = adapter or NullVisionAdapter()
        self.unavailable_reason = unavailable_reason

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        if self.unavailable_reason:
            return {"status": "unavailable", "reason": self.unavailable_reason}
        try:
            image, sent_width, sent_height = _downscale(capture)
            prompt = f"{VISION_PROMPT}\nA imagem tem {sent_width}x{sent_height} pixels."
            response = self.adapter.analyze(image, prompt)
            if not (response.text or "").strip():
                status = str(response.data.get("status") or "failed") if response.data else "failed"
                reason = response.data.get("reason") if response.data else None
                return {"status": status if status != "ok" else "failed", "reason": reason or "Resposta de visão vazia"}
            data = _parse_json(response.text)
            if not isinstance(data, dict):
                return {"status": "failed", "error": "Resposta de visão não é um objeto JSON"}
            scale_x = capture.width / sent_width if sent_width else 1.0
            scale_y = capture.height / sent_height if sent_height else 1.0
            return {
                "status": "ok",
                "summary": str(data.get("summary", "")),
                "foreground_target": data.get("foreground_target"),
                "ocr_text": str(data.get("ocr_text", "")),
                "elements": _sanitize_elements(
                    data.get("elements", []),
                    scale_x=scale_x,
                    scale_y=scale_y,
                    bounds=(capture.width, capture.height),
                ),
            }
        except Exception as exc:
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _downscale(capture: ScreenCapture) -> tuple[Any, int, int]:
    image = capture.image
    width, height = capture.width, capture.height
    if width <= MAX_SENT_WIDTH or not hasattr(image, "resize"):
        return image, width, height
    sent_height = max(1, round(height * MAX_SENT_WIDTH / width))
    return image.resize((MAX_SENT_WIDTH, sent_height)), MAX_SENT_WIDTH, sent_height


def _parse_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    return json.loads(cleaned)


def _sanitize_elements(
    elements: Any,
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    bounds: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(elements, list):
        return []

    clean: list[dict[str, Any]] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        try:
            x = round(float(item["x"]) * scale_x)
            y = round(float(item["y"]) * scale_y)
            width = max(0, round(float(item["width"]) * scale_x))
            height = max(0, round(float(item["height"]) * scale_y))
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except (KeyError, TypeError, ValueError):
            continue
        if bounds is not None:
            max_x, max_y = bounds
            # Coordenadas fora da imagem são alucinação do modelo: descarta.
            if x < 0 or y < 0 or x >= max_x or y >= max_y:
                continue
            width = min(width, max_x - x)
            height = min(height, max_y - y)
        clean.append(
            {
                "type": str(item.get("type", "other")),
                "text": str(item.get("text", "")),
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "confidence": confidence,
            }
        )
    return clean
