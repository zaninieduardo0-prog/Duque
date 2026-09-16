from __future__ import annotations

import json
import os
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
As coordenadas devem ser absolutas na imagem, com origem no canto superior esquerdo.
""".strip()


class ModelVisionAnalyzer(ScreenAnalyzer):
    """Adiciona visão multimodal opcional à percepção local do Windows."""

    def __init__(self, adapter: VisionAdapter | None = None) -> None:
        self.adapter = adapter or NullVisionAdapter()

    def analyze(self, capture: ScreenCapture) -> dict[str, Any]:
        if os.getenv("DUQUE_ENABLE_MODEL_VISION", "0").casefold() not in {"1", "true", "yes", "on"}:
            return {"status": "disabled", "reason": "DUQUE_ENABLE_MODEL_VISION is not enabled"}

        try:
            response = self.adapter.analyze(capture.image, VISION_PROMPT)
            data = _parse_json(response.text)
            if not isinstance(data, dict):
                return {"status": "failed", "error": "Resposta de visão não é um objeto JSON"}
            return {
                "status": "ok",
                "summary": str(data.get("summary", "")),
                "foreground_target": data.get("foreground_target"),
                "ocr_text": str(data.get("ocr_text", "")),
                "elements": _sanitize_elements(data.get("elements", [])),
            }
        except Exception as exc:
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _parse_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    return json.loads(cleaned)


def _sanitize_elements(elements: Any) -> list[dict[str, Any]]:
    if not isinstance(elements, list):
        return []

    clean: list[dict[str, Any]] = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        try:
            x = int(item["x"])
            y = int(item["y"])
            width = max(0, int(item["width"]))
            height = max(0, int(item["height"]))
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except (KeyError, TypeError, ValueError):
            continue
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
